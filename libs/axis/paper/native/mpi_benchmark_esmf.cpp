// SPDX-License-Identifier: Apache-2.0
#include <ESMC.h>

#ifdef _OPENMP
#include <omp.h>
#endif

#include "mpi_benchmark_common.hpp"

namespace {
using namespace paper;
using namespace paper::mpi_benchmark;

void check(int status, const char *operation) {
    if (status != ESMF_SUCCESS) {
        std::cerr << operation << " returned ESMC error " << status << '\n';
        MPI_Abort(MPI_COMM_WORLD, 5);
    }
}

class NativeMesh {
   public:
    NativeMesh(const Mesh &mesh, const NodeOwnership &nodes) {
        int status;
        auto coordinates = ESMC_COORDSYS_SPH_DEG;
        value = ESMC_MeshCreate(2, 2, &coordinates, &status);
        check(status, "ESMC_MeshCreate");

        auto node_ids = nodes.ids;
        auto owners = nodes.owners;
        std::vector<double> positions(2 * mesh.lon.size());
        for (std::size_t node = 0; node < mesh.lon.size(); ++node) {
            ++node_ids[node];
            positions[2 * node] = mesh.lon[node];
            positions[2 * node + 1] = mesh.lat[node];
        }
        check(ESMC_MeshAddNodes(value, node_ids.size(), node_ids.data(), positions.data(),
                                 owners.data(), nullptr), "ESMC_MeshAddNodes");

        auto indices = mesh.indices;
        auto cell_ids = mesh.ids;
        auto mask = mesh.mask;
        auto areas = mesh.area;
        std::vector<int> types(mesh.size());
        std::vector<double> centers(2 * mesh.size());
        for (std::size_t cell = 0; cell < mesh.size(); ++cell) {
            ++cell_ids[cell];
            types[cell] = mesh.offsets[cell + 1] - mesh.offsets[cell];
            centers[2 * cell] = mesh.center_lon[cell];
            centers[2 * cell + 1] = mesh.center_lat[cell];
        }
        for (auto &index : indices)
            ++index;
        check(ESMC_MeshAddElements(value, mesh.size(), cell_ids.data(), types.data(),
                                    indices.data(), mask.data(), areas.data(), centers.data()),
              "ESMC_MeshAddElements");
    }

    ~NativeMesh() { ESMC_MeshDestroy(&value); }
    NativeMesh(const NativeMesh &) = delete;

    ESMC_Mesh value{};
};

class NativeField {
   public:
    explicit NativeField(ESMC_Mesh mesh) {
        int status;
        value = ESMC_FieldCreateMeshTypeKind(mesh, ESMC_TYPEKIND_R8, ESMC_MESHLOC_ELEMENT,
                                             nullptr, nullptr, nullptr, nullptr, &status);
        check(status, "ESMC_FieldCreateMeshTypeKind");
    }

    ~NativeField() { ESMC_FieldDestroy(&value); }
    NativeField(const NativeField &) = delete;

    double *data() const {
        int status;
        auto values = static_cast<double *>(ESMC_FieldGetPtr(value, 0, &status));
        check(status, "ESMC_FieldGetPtr");
        return values;
    }

    ESMC_Field value{};
};

class ESMFEngine {
   public:
    ESMFEngine(const Fixture &fixture, bool conservative)
        : fixture_(fixture), conservative_(conservative),
          src_mesh_(fixture.data.src, fixture.source_nodes),
          dst_mesh_(fixture.data.dst, fixture.destination_nodes),
          src_(src_mesh_.value), dst_(dst_mesh_.value), mask_(fixture.data.dst),
          destination_(dst_.data()) {
        std::copy(fixture.source.begin(), fixture.source.end(), src_.data());
        if (conservative_) {
            src_fraction_.emplace(src_mesh_.value);
            dst_fraction_.emplace(dst_mesh_.value);
        }
    }

    ~ESMFEngine() { release(); }
    ESMFEngine(const ESMFEngine &) = delete;

    void setup() {
        int masked = 0;
        ESMC_InterArrayInt mask;
        auto method = conservative_ ? ESMC_REGRIDMETHOD_CONSERVE : ESMC_REGRIDMETHOD_BILINEAR;
        auto line = ESMC_LINETYPE_GREAT_CIRCLE;
        auto norm = fixture_.data.norm == "fracarea" ? ESMC_NORMTYPE_FRACAREA : ESMC_NORMTYPE_DSTAREA;
        auto vector = ESMF_FALSE;
        auto pole = ESMC_POLEMETHOD_NONE;
        auto extrap = ESMC_EXTRAPMETHOD_NONE;
        auto unmapped = ESMC_UNMAPPEDACTION_IGNORE;
        auto degenerate = ESMF_FALSE;
        check(ESMC_InterArrayIntSet(&mask, &masked, 1), "ESMC_InterArrayIntSet");
        // Coverage fields are initialized explicitly because masked cells may not be set.
        if (conservative_) {
            std::fill_n(src_fraction_->data(), fixture_.source.size(), 0.0);
            std::fill_n(dst_fraction_->data(), fixture_.expected.size(), 0.0);
        }
        check(ESMC_FieldRegridStore(
                  src_.value, dst_.value, &mask, &mask, &route_, &method, &pole, nullptr,
                  &line, &norm, &vector, &extrap, nullptr, nullptr, nullptr, &unmapped, &degenerate,
                  nullptr, nullptr, nullptr, src_fraction_ ? &src_fraction_->value : nullptr,
                  dst_fraction_ ? &dst_fraction_->value : nullptr),
              "ESMC_FieldRegridStore");
        route_live_ = true;
    }

    void apply() {
        auto zero = ESMC_REGION_TOTAL;
        check(ESMC_FieldRegrid(src_.value, dst_.value, route_, &zero), "ESMC_FieldRegrid");
        mask_.apply(destination_);
    }

    void release() {
        if (route_live_) {
            check(ESMC_FieldRegridRelease(&route_), "ESMC_FieldRegridRelease");
            route_live_ = false;
        }
    }

    Result result() const {
        Result result{std::vector<double>(destination_, destination_ + fixture_.expected.size()), {}, {}};
        if (conservative_) {
            auto src_fraction = src_fraction_->data();
            auto dst_fraction = dst_fraction_->data();
            result.source_fraction.assign(src_fraction, src_fraction + fixture_.source.size());
            result.destination_fraction.assign(dst_fraction, dst_fraction + fixture_.expected.size());
        }
        return result;
    }

    int threads() const {
#ifdef _OPENMP
        return omp_get_max_threads();
#else
        return 1;
#endif
    }

   private:
    const Fixture &fixture_;
    bool conservative_;
    NativeMesh src_mesh_;
    NativeMesh dst_mesh_;
    NativeField src_;
    NativeField dst_;
    std::optional<NativeField> src_fraction_;
    std::optional<NativeField> dst_fraction_;
    DestinationMask mask_;
    double *destination_;
    ESMC_RouteHandle route_{};
    bool route_live_ = false;
};
}  // namespace

int main(int argc, char **argv) {
    int status;
    if (ESMC_Initialize(&status, ESMC_InitArgLogKindFlag(ESMC_LOGKIND_NONE), ESMC_ArgLast) != ESMF_SUCCESS ||
        status != ESMF_SUCCESS) {
        std::cerr << "ESMC_Initialize failed\n";
        return 5;
    }
    Context mpi;
    int result = 0;
    try {
        result = run<ESMFEngine>(mpi, Args(argc, argv), PAPER_ESMF_VERSION);
    } catch (const Error &error) {
        std::cerr << "Rank " << mpi.rank << ": " << error.what() << '\n';
        result = error.code;
    } catch (const std::exception &error) {
        std::cerr << "Rank " << mpi.rank << ": " << error.what() << '\n';
        MPI_Abort(MPI_COMM_WORLD, 5);
    }
    return ESMC_Finalize() == ESMF_SUCCESS ? result : 5;
}
