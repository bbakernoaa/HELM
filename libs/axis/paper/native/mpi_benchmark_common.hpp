// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <mpi.h>
#include <sys/resource.h>

#include <algorithm>
#include <climits>
#include <fstream>
#include <iomanip>
#include <limits>
#include <optional>
#include <set>

#include "case_io.hpp"
#include "timing.hpp"

namespace paper::mpi_benchmark {

struct Context {
    int rank = 0;
    int ranks = 0;

    Context() {
        MPI_Comm_rank(MPI_COMM_WORLD, &rank);
        MPI_Comm_size(MPI_COMM_WORLD, &ranks);
    }

    double reduce(double local, MPI_Op operation) const {
        double result = 0;
        MPI_Allreduce(&local, &result, 1, MPI_DOUBLE, operation, MPI_COMM_WORLD);
        return result;
    }

    template <class Work>
    void local_step(Work work) const {
        int status = 0;
        try {
            work();
        } catch (const Error &error) {
            status = error.code;
            std::cerr << "Rank " << rank << ": " << error.what() << '\n';
        } catch (const std::exception &error) {
            status = 5;
            std::cerr << "Rank " << rank << ": " << error.what() << '\n';
        }
        int global_status = 0;
        MPI_Allreduce(&status, &global_status, 1, MPI_INT, MPI_MAX, MPI_COMM_WORLD);
        if (global_status)
            throw Error(global_status, "MPI benchmark local phase failed; see rank diagnostics");
    }

    template <class Work>
    double measure(Work work) const {
        MPI_Barrier(MPI_COMM_WORLD);
        const auto start = Clock::now();
        work();
        const auto duration = std::chrono::duration<double>(Clock::now() - start).count();
        return reduce(duration, MPI_MAX);
    }

    template <class Work>
    double measure_local(Work work) const {
        MPI_Barrier(MPI_COMM_WORLD);
        double duration = 0;
        local_step([&] {
            const auto start = Clock::now();
            work();
            duration = std::chrono::duration<double>(Clock::now() - start).count();
        });
        return reduce(duration, MPI_MAX);
    }

    bool agrees_with_root(const std::string &text) const {
        int length = rank == 0 ? static_cast<int>(text.size()) : 0;
        MPI_Bcast(&length, 1, MPI_INT, 0, MPI_COMM_WORLD);
        std::string root(static_cast<std::size_t>(length), '\0');
        if (rank == 0)
            root = text;
        MPI_Bcast(root.data(), length, MPI_CHAR, 0, MPI_COMM_WORLD);
        return reduce(text == root ? 1. : 0., MPI_MIN) == 1.;
    }

    std::set<std::string> hosts() const {
        char host[MPI_MAX_PROCESSOR_NAME + 1]{};
        int length = 0;
        MPI_Get_processor_name(host, &length);
        std::vector<char> names(ranks * sizeof(host));
        MPI_Allgather(host, static_cast<int>(sizeof(host)), MPI_CHAR, names.data(),
                      static_cast<int>(sizeof(host)), MPI_CHAR, MPI_COMM_WORLD);
        std::set<std::string> result;
        for (int index = 0; index < ranks; ++index)
            result.emplace(names.data() + index * sizeof(host));
        return result;
    }
};

inline std::optional<std::vector<double>> optional_field(int group_id, const char *name,
                                                         std::size_t count, double tolerance) {
    int variable;
    const int status = nc_inq_varid(group_id, name, &variable);
    if (status == NC_ENOTVAR)
        return std::nullopt;
    nc_check(status);
    auto values = doubles(group_id, name);
    if (values.size() != count || !std::ranges::all_of(values, [tolerance](double value) {
            return std::isfinite(value) && value >= 0 && value <= 1 + tolerance;
        }))
        throw Error(2, "Invalid fixture fractional coverage");
    return values;
}

struct NodeOwnership {
    std::vector<int> ids;
    std::vector<int> owners;
};

inline NodeOwnership read_ownership(int group_id, const Mesh &mesh, int ranks) {
    NodeOwnership nodes{integers(group_id, "node_id"), integers(group_id, "node_owner")};
    if (nodes.ids.size() != mesh.lon.size() || nodes.owners.size() != nodes.ids.size() ||
        std::set<int>(nodes.ids.begin(), nodes.ids.end()).size() != nodes.ids.size() ||
        !std::ranges::all_of(nodes.ids, [](int id) { return id >= 0 && id < INT_MAX; }) ||
        !std::ranges::all_of(nodes.owners, [ranks](int rank) { return rank >= 0 && rank < ranks; }))
        throw Error(2, "Invalid fixture node IDs or owners");
    if (!std::ranges::all_of(mesh.ids, [](int id) { return id >= 0 && id < INT_MAX; }) ||
        !std::ranges::all_of(mesh.mask, [](int mask) { return mask == 0 || mask == 1; }) ||
        !std::ranges::all_of(mesh.center_lon, [](double value) { return std::isfinite(value); }) ||
        !std::ranges::all_of(mesh.center_lat, [](double value) { return std::isfinite(value) && std::abs(value) <= 90; }))
        throw Error(2, "Invalid fixture cell IDs, centers or mask");
    for (std::size_t cell = 0; cell < mesh.size(); ++cell) {
        const int vertices = mesh.offsets[cell + 1] - mesh.offsets[cell];
        if (vertices != 3 && vertices != 4)
            throw Error(4, "Matched MPI fixtures require triangular or quadrilateral cells");
    }
    return nodes;
}

struct Fixture {
    Case data;
    NodeOwnership source_nodes;
    NodeOwnership destination_nodes;
    std::vector<double> source;
    std::vector<double> expected;
    std::optional<std::vector<double>> expected_source_fraction;
    std::optional<std::vector<double>> expected_destination_fraction;
    double tolerance;
};

inline Fixture read_fixture(const std::filesystem::path &path, int ranks) {
    auto data = read_case(path);
    if (data.geometry != "great_circle")
        throw Error(4, "Matched MPI fixtures require spherical great-circle edges");
    File file(path);
    if (attr(file.id, "ranks") != std::to_string(ranks))
        throw Error(2, "Fixture shard count does not match MPI rank count");
    auto source = group(file.id, "source");
    auto destination = group(file.id, "destination");
    auto source_nodes = read_ownership(source, data.src, ranks);
    auto destination_nodes = read_ownership(destination, data.dst, ranks);
    auto field = doubles(source, "field");
    auto expected = doubles(destination, "expected");
    auto finite = [](double value) { return std::isfinite(value); };
    if (field.size() != data.src.size() || expected.size() != data.dst.size() ||
        !std::ranges::all_of(field, finite) || !std::ranges::all_of(expected, finite))
        throw Error(2, "Invalid fixture field or expected data");
    const auto tolerance_text = attr(file.id, "benchmark_abs_tolerance", "1e-8");
    std::size_t consumed = 0;
    double tolerance = std::stod(tolerance_text, &consumed);
    if (consumed != tolerance_text.size() || !std::isfinite(tolerance) || tolerance <= 0)
        throw Error(2, "Invalid fixture absolute tolerance");
    auto expected_source = optional_field(source, "expected_fraction", data.src.size(), tolerance);
    auto expected_destination = optional_field(destination, "expected_fraction", data.dst.size(),
                                               tolerance);
    return {std::move(data), std::move(source_nodes), std::move(destination_nodes),
            std::move(field), std::move(expected), std::move(expected_source),
            std::move(expected_destination), tolerance};
}

struct Result {
    std::vector<double> destination;
    std::vector<double> source_fraction;
    std::vector<double> destination_fraction;
};

class DestinationMask {
   public:
    explicit DestinationMask(const Mesh &mesh) {
        for (std::size_t cell = 0; cell < mesh.size(); ++cell)
            if (!mesh.mask[cell])
                inactive_.push_back(cell);
    }

    // Some point interpolation paths do not zero inactive destination cells.
    // Both engines include the same explicit destination masking in apply.
    void apply(double *values) const {
        for (auto cell : inactive_)
            values[cell] = 0.0;
    }

   private:
    std::vector<std::size_t> inactive_;
};

inline double local_max_error(const std::vector<double> &left, const std::vector<double> &right) {
    if (left.size() != right.size())
        return std::numeric_limits<double>::infinity();
    double result = 0;
    for (std::size_t index = 0; index < left.size(); ++index) {
        if (!std::isfinite(left[index]))
            return std::numeric_limits<double>::infinity();
        result = std::max(result, std::abs(left[index] - right[index]));
    }
    return result;
}

inline double covered_integral(const std::vector<double> &field, const std::vector<double> &area,
                               const std::vector<double> *fraction) {
    double result = 0;
    for (std::size_t cell = 0; cell < field.size(); ++cell)
        result += field[cell] * area[cell] * (fraction ? (*fraction)[cell] : 1.0);
    return result;
}

struct Quality {
    double max_error;
    double area_weighted_rmse;
    double source_fraction_error;
    double destination_fraction_error;
    double source_integral;
    double destination_integral;
    double conservation_error;
    bool passed;
};

inline Quality assess(const Context &mpi, const Fixture &fixture, const Result &result,
                      bool conservative) {
    mpi.local_step([&] {
        if (result.destination.size() != fixture.expected.size() ||
            (conservative &&
             (result.source_fraction.size() != fixture.source.size() ||
              result.destination_fraction.size() != fixture.expected.size())))
            throw Error(5, "Unexpected native output extents");
    });
    auto max_error = mpi.reduce(local_max_error(result.destination, fixture.expected), MPI_MAX);
    double error_sum = 0, area_sum = 0;
    for (std::size_t index = 0; index < result.destination.size(); ++index) {
        const double error = result.destination[index] - fixture.expected[index];
        error_sum += fixture.data.dst.area[index] * error * error;
        area_sum += fixture.data.dst.area[index];
    }
    auto rmse = std::sqrt(mpi.reduce(error_sum, MPI_SUM) / mpi.reduce(area_sum, MPI_SUM));
    const double unavailable = std::numeric_limits<double>::quiet_NaN();
    double src_error = unavailable, dst_error = unavailable;
    double src_int = unavailable, dst_int = unavailable, conservation_error = unavailable;
    bool passed = max_error <= fixture.tolerance;
    if (conservative) {
        auto coverage_error = [&](const std::vector<double> &actual,
                                  const std::optional<std::vector<double>> &expected) {
            // Every rank always participates, even when there is no coverage oracle.
            const double local = expected ? local_max_error(actual, *expected) : -1;
            const double maximum = mpi.reduce(local, MPI_MAX);
            return maximum >= 0 ? maximum : unavailable;
        };
        src_error = coverage_error(result.source_fraction, fixture.expected_source_fraction);
        dst_error = coverage_error(result.destination_fraction, fixture.expected_destination_fraction);
        src_int = mpi.reduce(covered_integral(fixture.source, fixture.data.src.area,
                                             &result.source_fraction), MPI_SUM);
        dst_int = mpi.reduce(covered_integral(result.destination, fixture.data.dst.area,
                                              fixture.data.norm == "fracarea"
                                                  ? &result.destination_fraction : nullptr), MPI_SUM);
        conservation_error = std::abs(src_int - dst_int) / std::max(1., std::abs(src_int));
        passed = passed && (!std::isfinite(src_error) ? std::isnan(src_error) : src_error <= fixture.tolerance) &&
                 (!std::isfinite(dst_error) ? std::isnan(dst_error) : dst_error <= fixture.tolerance) &&
                 conservation_error <= fixture.data.conservation_tolerance;
    }
    return {max_error, rmse, src_error, dst_error, src_int, dst_int, conservation_error, passed};
}

inline void write_destination(const std::filesystem::path &path, const Fixture &fixture,
                              const Result &result) {
    const auto temporary = path.string() + ".tmp";
    {
        std::ofstream stream(temporary);
        stream << "cell_id,value,expected,fraction\n" << std::setprecision(17);
        for (std::size_t index = 0; index < result.destination.size(); ++index) {
            stream << fixture.data.dst.ids[index] << ',' << result.destination[index] << ','
                   << fixture.expected[index] << ',';
            if (index < result.destination_fraction.size())
                stream << result.destination_fraction[index];
            stream << '\n';
        }
        stream.flush();
        if (!stream)
            throw Error(5, "Could not write " + temporary);
    }
    std::filesystem::rename(temporary, path);
}

inline void write_quality(const std::filesystem::path &path, const Context &mpi,
                          const Fixture &fixture, const Quality &quality,
                          const std::string &engine_version, const std::string &method,
                          int threads) {
    auto hosts = mpi.hosts();
    const double min_threads = mpi.reduce(threads, MPI_MIN);
    const double max_threads = mpi.reduce(threads, MPI_MAX);
    rusage usage{};
    const bool has_rss = getrusage(RUSAGE_SELF, &usage) == 0;
#ifdef __APPLE__
    constexpr double rss_factor = 1.;
#else
    constexpr double rss_factor = 1024.;
#endif
    const double rss = mpi.reduce(has_rss ? usage.ru_maxrss * rss_factor : -1., MPI_MAX);
    mpi.local_step([&] {
        if (mpi.rank != 0)
            return;
        char mpi_version[MPI_MAX_LIBRARY_VERSION_STRING]{};
        int version_length = 0;
        MPI_Get_library_version(mpi_version, &version_length);
        std::ostringstream json;
        json << "{\"passed\":" << (quality.passed ? "true" : "false")
             << ",\"case_id\":" << quote(fixture.data.id)
             << ",\"method\":" << quote(method)
             << ",\"normalization\":" << quote(fixture.data.norm)
             << ",\"engine_version\":" << quote(engine_version)
             << ",\"mpi_version\":" << quote(mpi_version)
             << ",\"max_abs_error\":" << number(quality.max_error)
             << ",\"area_weighted_rmse\":" << number(quality.area_weighted_rmse)
             << ",\"abs_tolerance\":" << number(fixture.tolerance)
             << ",\"source_fraction_max_error\":" << number(quality.source_fraction_error)
             << ",\"destination_fraction_max_error\":" << number(quality.destination_fraction_error)
             << ",\"source_integral\":" << number(quality.source_integral)
             << ",\"destination_integral\":" << number(quality.destination_integral)
             << ",\"conservation_error\":" << number(quality.conservation_error)
             << ",\"peak_rank_rss_bytes\":" << (rss < 0 ? "null" : number(rss))
             << ",\"ranks\":" << mpi.ranks << ",\"threads_min\":" << min_threads
             << ",\"threads_max\":" << max_threads << ",\"hosts\":[";
        for (auto host = hosts.begin(); host != hosts.end(); ++host) {
            if (host != hosts.begin())
                json << ',';
            json << quote(*host);
        }
        json << "]}";
        atomic_text(path, json.str());
    });
}

template <class Engine>
int run(const Context &mpi, const Args &args, const std::string &version) {
    const std::filesystem::path output = args.require("output");
    const std::filesystem::path shards = args.require("fixture");
    auto method = args.get("method", "conservative");
    if (method == "conservative_first_order")
        method = "conservative";
    if (method != "conservative" && method != "bilinear")
        throw Error(4, "Matched MPI benchmark supports bilinear and first-order conservative");
    const bool conservative = method == "conservative";
    const int warmups = args.count("warmups", 2);
    const int repetitions = args.count("repetitions", 3);
    const auto reuse = reuse_counts(args);
    if (std::set<int>(reuse.begin(), reuse.end()).size() != reuse.size())
        throw Error(2, "Duplicate reuse count");

    mpi.local_step([&] {
        if (mpi.rank == 0) {
            std::filesystem::create_directories(output);
            if (std::filesystem::exists(output / "observations.csv"))
                throw Error(2, "Output already contains native observations");
        }
    });
    std::vector<Observation> samples;
    auto record = [&](int repetition, std::string phase, int applications, double seconds) {
        mpi.local_step([&] {
            if (mpi.rank == 0) {
                samples.push_back({repetition, std::move(phase), applications, seconds});
                observations(output / "observations.csv", samples);
            }
        });
    };

    std::optional<Fixture> fixture;
    const auto ingest_seconds = mpi.measure_local([&] {
        fixture = read_fixture(shards / ("rank-" + std::to_string(mpi.rank) + ".nc"), mpi.ranks);
    });
    record(0, "fixture_ingest", 0, ingest_seconds);
    // Divergent shard settings would make the engines run different collective operations.
    mpi.local_step([&] {
        if (fixture->data.id.empty() || fixture->data.id.size() > INT_MAX)
            throw Error(2, "Missing or invalid fixture case ID");
        if (!std::isfinite(fixture->data.conservation_tolerance) ||
            fixture->data.conservation_tolerance <= 0)
            throw Error(2, "Invalid fixture conservation tolerance");
    });
    const int fracarea = fixture->data.norm == "fracarea";
    if (!mpi.agrees_with_root(fixture->data.id) ||
        mpi.reduce(fracarea, MPI_MIN) != mpi.reduce(fracarea, MPI_MAX) ||
        mpi.reduce(fixture->tolerance, MPI_MIN) != mpi.reduce(fixture->tolerance, MPI_MAX) ||
        mpi.reduce(fixture->data.conservation_tolerance, MPI_MIN) !=
            mpi.reduce(fixture->data.conservation_tolerance, MPI_MAX))
        throw Error(2, "Fixture shard attributes disagree");

    std::optional<Engine> engine;
    auto prepare_seconds = mpi.measure([&] { engine.emplace(*fixture, conservative); });
    record(0, "mesh_finalize", 0, prepare_seconds);
    for (int repetition = -warmups; repetition < repetitions; ++repetition) {
        engine->release();
        const auto setup = mpi.measure([&] { engine->setup(); });
        const auto first_apply = mpi.measure([&] { engine->apply(); });
        if (repetition < 0)
            continue;
        record(repetition, "setup", 0, setup);
        record(repetition, "operator_finalize", 1, first_apply);
        const auto apply = mpi.measure([&] { engine->apply(); });
        record(repetition, "apply", 1, apply);
        for (int applications : reuse) {
            const auto reused = mpi.measure([&] {
                for (int iteration = 0; iteration < applications; ++iteration)
                    engine->apply();
            });
            record(repetition, "repeated_workload", applications, reused);
            record(repetition, "setup_and_reuse", applications, setup + first_apply + reused);
        }
    }
    Result result;
    mpi.local_step([&] { result = engine->result(); });
    const auto quality = assess(mpi, *fixture, result, conservative);
    const auto output_seconds = mpi.measure_local([&] {
        write_destination(output / ("destination-" + std::to_string(mpi.rank) + ".csv"),
                          *fixture, result);
    });
    record(0, "output_write", 0, output_seconds);
    write_quality(output / "native_quality.json", mpi, *fixture, quality, version, method,
                  engine->threads());
    return quality.passed ? 0 : 6;
}

}  // namespace paper::mpi_benchmark
