// SPDX-License-Identifier: Apache-2.0
#include <Kokkos_Core.hpp>
#include <axis/distributed/regridder.hpp>
#include <axis/topology/mesh_builder.hpp>

#include "build_info.hpp"
#include "mpi_benchmark_common.hpp"

namespace {
using namespace paper;
using namespace paper::mpi_benchmark;
using Space = Kokkos::HostSpace;

template <class T>
auto copy_view(const char *label, const std::vector<T> &values) {
    Kokkos::View<T *, Space> view(label, values.size());
    std::copy(values.begin(), values.end(), view.data());
    return view;
}

auto mesh_from_fixture(const Mesh &mesh) {
    using namespace axis::topology;
    Kokkos::View<double **, Kokkos::LayoutLeft, Space> nodes("nodes", mesh.lon.size(), 2);
    for (std::size_t index = 0; index < mesh.lon.size(); ++index) {
        nodes(index, 0) = mesh.lon[index];
        nodes(index, 1) = mesh.lat[index];
    }
    const std::vector<axis::index_t> offsets(mesh.offsets.begin(), mesh.offsets.end());
    const std::vector<axis::index_t> indices(mesh.indices.begin(), mesh.indices.end());
    GeometryMetadata geometry;
    geometry.provenance = GeometryProvenance::SourceAuthoritative;
    geometry.boundary_model = BoundaryModel::GreatCircle;
    geometry.area_model = AreaModel::SphericalExcess;
    return make_unstructured<Space>(
        nodes, copy_view("offsets", offsets), copy_view("indices", indices),
        CoordinateSystem::SphericalDeg, copy_view("areas", mesh.area),
        copy_view("mask", mesh.mask), geometry);
}

class AxisEngine {
   public:
    AxisEngine(const Fixture &fixture, bool conservative)
        : fixture_(fixture), conservative_(conservative), src_(mesh_from_fixture(fixture.data.src)),
          dst_(mesh_from_fixture(fixture.data.dst)),
          node_ids_(fixture.source_nodes.ids.begin(), fixture.source_nodes.ids.end()),
          destination_(fixture.expected.size()), mask_(fixture.data.dst) {}

    void setup() {
        using namespace axis::solver;
        RegridConfig config;
        config.method = conservative_ ? InterpolationMethod::Conservative1stOrder
                                      : InterpolationMethod::Bilinear;
        config.line_type = LineType::GreatCircle;
        config.norm_type = fixture_.data.norm == "fracarea" ? NormType::FracArea : NormType::DstArea;
        config.extrap_method = ExtrapolationAction::None;
        config.unmapped = UnmappedAction::Ignore;
        op_.emplace(src_, dst_, config, MPI_COMM_WORLD, node_ids_);
        Kokkos::fence();
    }

    void apply() {
        op_->apply(axis::field_view<const double, 1>(fixture_.source.data(), fixture_.source.size()),
                   axis::field_view<double, 1>(destination_.data(), destination_.size()));
        Kokkos::fence();
        mask_.apply(destination_.data());
    }

    void release() { op_.reset(); }

    Result result() const {
        if (!conservative_)
            return {destination_, {}, {}};
        auto coverage = op_->local_matrix().frac_b();
        std::vector<double> fraction(coverage.extent(0));
        for (std::size_t index = 0; index < fraction.size(); ++index)
            fraction[index] = coverage[index];
        return {destination_, op_->owned_source_fractions(), std::move(fraction)};
    }

    int threads() const { return Kokkos::DefaultHostExecutionSpace().concurrency(); }

   private:
    const Fixture &fixture_;
    bool conservative_;
    axis::topology::UnstructuredMesh<Space> src_;
    axis::topology::UnstructuredMesh<Space> dst_;
    std::vector<long long> node_ids_;
    std::vector<double> destination_;
    DestinationMask mask_;
    std::optional<axis::distributed::DistributedRegridder> op_;
};
}  // namespace

int main(int argc, char **argv) {
    int provided = 0;
    if (MPI_Init_thread(&argc, &argv, MPI_THREAD_FUNNELED, &provided) != MPI_SUCCESS)
        return 5;
    if (provided < MPI_THREAD_FUNNELED) {
        std::cerr << "MPI_THREAD_FUNNELED support is required\n";
        MPI_Abort(MPI_COMM_WORLD, 5);
    }
    Context mpi;
    int status = 0;
    try {
        Kokkos::ScopeGuard kokkos;
        status = run<AxisEngine>(mpi, Args(argc, argv), PAPER_COMMIT);
    } catch (const Error &error) {
        std::cerr << "Rank " << mpi.rank << ": " << error.what() << '\n';
        status = error.code;
    } catch (const std::exception &error) {
        std::cerr << "Rank " << mpi.rank << ": " << error.what() << '\n';
        MPI_Abort(MPI_COMM_WORLD, 5);
    }
    MPI_Finalize();
    return status;
}
