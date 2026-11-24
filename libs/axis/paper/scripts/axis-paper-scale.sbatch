#!/usr/bin/env bash
#SBATCH --job-name=axis-paper
#SBATCH --output=%x-%j.out
#SBATCH --time=01:00:00
#SBATCH --exclusive

set -euo pipefail

usage() {
    echo "Usage: $0 mpi strong|weak NX NY METHOD | paper PROFILE CASES | matched SITE AXIS_CASE ESMF_CASE" >&2
    exit 2
}

: "${SLURM_JOB_ID:?Submit with sbatch}"
: "${AXIS_REPO:?Set AXIS_REPO to the HELM checkout}"
: "${AXIS_BUILD:?Set AXIS_BUILD to the CMake build directory}"
: "${AXIS_RESULTS:?Set AXIS_RESULTS to a shared results directory}"

mode=${1:-}
case "$mode" in
    mpi) [[ $# == 5 && ( $2 == strong || $2 == weak ) ]] || usage ;;
    paper) [[ $# == 3 ]] || usage ;;
    matched)
        [[ $# == 4 ]] || usage
        site=$(realpath -e "$2")
        axis_case=$(realpath -e "$3")
        esmf_case=$(realpath -e "$4")
        ;;
    *) usage ;;
esac

run_dir="$AXIS_RESULTS/${SLURM_CLUSTER_NAME:-slurm}-${SLURM_JOB_ID}"
mkdir -p "$AXIS_RESULTS"
mkdir "$run_dir"
cd "$run_dir"

# Set this only if the module stack needs an explicit Slurm MPI plugin.
mpi_options=()
if [[ -n ${AXIS_SLURM_MPI:-} ]]; then
    mpi_options+=(--mpi="$AXIS_SLURM_MPI")
fi

{
    date -u +%FT%TZ
    printf 'Command:'
    printf ' %q' "$@"
    printf '\n'
    git -C "$AXIS_REPO" rev-parse HEAD
    git -C "$AXIS_REPO" status --short
    scontrol show job "$SLURM_JOB_ID"
    if type module >/dev/null 2>&1; then module list 2>&1; fi
    cp "$AXIS_BUILD/CMakeCache.txt" .
    scontrol show hostnames "$SLURM_JOB_NODELIST" > hosts.txt
} > provenance.txt 2>&1

threads=${SLURM_CPUS_PER_TASK:-1}
nodes=$SLURM_JOB_NUM_NODES
ranks=$SLURM_NTASKS
export OMP_NUM_THREADS=$threads KOKKOS_NUM_THREADS=$threads
export OMP_PLACES=cores OMP_PROC_BIND=close

if [[ $mode == matched ]]; then
    python_bin=${AXIS_PYTHON:-python3}
    "$python_bin" - "$axis_case" "$esmf_case" <<'PYTHON'
import json
import sys
from pathlib import Path

axis_path, esmf_path = map(Path, sys.argv[1:])
axis = json.loads(axis_path.read_text())
esmf = json.loads(esmf_path.read_text())
if axis["engine"] != "axis" or esmf["engine"] != "esmf":
    raise SystemExit("Provide the AXIS case first and the ESMF case second.")
if (axis_path.parent / axis["fixture"]).resolve() != (esmf_path.parent / esmf["fixture"]).resolve():
    raise SystemExit("Matched cases must reference the same fixture manifest.")
for key in ("fixture_id", "workload_id", "scaling", "method", "normalization", "edge_model",
            "unmapped", "precision", "timing_scope", "repetitions", "warmups", "reuse"):
    if axis.get(key) != esmf.get(key):
        raise SystemExit(f"Matched cases differ in {key}.")
PYTHON
    launches=${AXIS_LAUNCHES:-3}
    [[ $launches =~ ^[1-9][0-9]*$ ]] || { echo 'AXIS_LAUNCHES must be positive.' >&2; exit 2; }
    # Alternate execution order within each allocation and vary the first engine by job.
    job_hash=$(printf '%s' "${SLURM_CLUSTER_NAME:-slurm}-$SLURM_JOB_ID" | sha256sum)
    first_engine=$((16#${job_hash:0:1} % 2))
    failed=0
    for ((sample=1; sample<=launches; sample++)); do
        launch_dir="$run_dir/launch-$sample"
        mkdir "$launch_dir"
        engine_order=(axis esmf)
        if (((first_engine + sample - 1) % 2)); then engine_order=(esmf axis); fi
        printf '%s\n' "${engine_order[@]}" > "$launch_dir/engine-order.txt"
        for engine in "${engine_order[@]}"; do
            case_file=$axis_case
            if [[ $engine == esmf ]]; then case_file=$esmf_case; fi
            AXIS_MPI_LAUNCH_ID="$sample" "$python_bin" \
                "$AXIS_REPO/libs/axis/paper/scripts/benchmark.py" mpi \
                --site "$site" --case "$case_file" --build-dir "$AXIS_BUILD" \
                --output "$launch_dir/$engine" --nodes "$nodes" --ranks "$ranks" --threads "$threads" --live \
                > "$launch_dir/$engine.stdout" 2> "$launch_dir/$engine.stderr" || failed=1
        done
    done
    exit "$failed"
fi

if [[ $mode == paper ]]; then
    [[ $nodes == 1 && $ranks == 1 ]] || {
        echo 'Paper timing requires one node and one task.' >&2
        exit 2
    }
    python_bin=${AXIS_PYTHON:-python3}
    profile_threads=$("$python_bin" -c 'import json,sys; print(json.load(open(sys.argv[1]))["threads"])' "$2")
    [[ $profile_threads == "$threads" ]] || {
        echo "Request --cpus-per-task=$profile_threads for this profile." >&2
        exit 2
    }
    for worker in axis esmc reference metrics; do
        test -x "$AXIS_BUILD/paper/axis_paper_$worker"
        sha256sum "$AXIS_BUILD/paper/axis_paper_$worker" >> provenance.txt
    done
    "$python_bin" --version >> provenance.txt 2>&1
    srun --nodes=1 --ntasks=1 --cpus-per-task="$threads" --cpu-bind=cores \
        "${mpi_options[@]}" "$python_bin" "$AXIS_REPO/libs/axis/paper/scripts/run_suite.py" \
        --profile "$2" --cases "$3" --bin-dir "$AXIS_BUILD/paper" --output "$run_dir/suite"
    exit
fi

binary="$AXIS_BUILD/benchmarks/axis_distributed_scaling"
test -x "$binary"
sha256sum "$binary" >> provenance.txt
launches=${AXIS_LAUNCHES:-3}
[[ $launches =~ ^[1-9][0-9]*$ ]] || { echo 'AXIS_LAUNCHES must be positive.' >&2; exit 2; }

for ((sample=1; sample<=launches; sample++)); do
    srun --nodes="$nodes" --ntasks="$ranks" --cpus-per-task="$threads" \
        --distribution=block:block --cpu-bind=cores "${mpi_options[@]}" "$binary" \
        "$3" "$4" "${AXIS_APPLY_REPS:-15}" "$5" "${AXIS_FIELDS:-8}" "$2" \
        > "launch-$sample.stdout" 2> "launch-$sample.stderr"

    awk -F, -v mode="$2" -v method="$5" -v nodes="$nodes" -v ranks="$ranks" \
        -v threads="$threads" '
        $1 == "mode" { header = $0 }
        $1 == mode && $2 == method {
            if ($4 != nodes || $5 != ranks || $6 != threads || $7 != threads) bad = 1
            row = $0
            count++
        }
        END {
            if (!header || count != 1 || bad) exit 1
            print header
            print row
        }' "launch-$sample.stdout" > "launch-$sample.csv" || {
            echo "Missing benchmark output or unexpected MPI/OpenMP layout in launch $sample." >&2
            exit 1
        }
done
