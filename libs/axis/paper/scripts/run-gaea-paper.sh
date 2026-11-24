#!/usr/bin/env bash
# Submit and monitor the AXIS paper pilot on Gaea C6.
set -euo pipefail

if [[ ${1:-} == --internal-* ]]; then
    : "${AXIS_REPO:?Missing exported repository path}"
    repo=$AXIS_REPO
    script_dir="$repo/libs/axis/paper/scripts"
else
    script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
    repo=$(git -C "$script_dir" rev-parse --show-toplevel)
fi
paper="$repo/libs/axis/paper"
benchmark="$paper/scripts/benchmark.py"

usage() {
    cat <<'HELP'
Usage: bash libs/axis/paper/scripts/run-gaea-paper.sh --account PROJECT --site SITE.json [options]

Run on a Gaea submit host with the desired compiler, MPI, ESMF and Python modules
already loaded. Set ESMFMKFILE to the compatible ESMF installation. SITE.json is
a copy of config/slurm/gaea-c6.example.json with account, interfaces, spill path,
and worker module setup filled in. The Python environment needs AXIS, xESMF,
ESMPy, dask-jobqueue, Jupyter and paper benchmark dependencies.

Options:
  --account PROJECT    Gaea allocation account (required)
  --site FILE          Configured Dask Slurm profile (required for a live run)
  --output DIR         New shared filesystem output directory
  --python FILE        Python executable (default: python3 from loaded environment)
  --build-dir DIR      CMake build directory (default: OUTPUT/build)
  --nodes LIST         Comma-separated node counts (default: 1,2)
  --ranks-per-node N   MPI ranks and Dask processes per worker node (default: 4)
  --nx N --ny N        Identity grid dimensions (default: 128 by 128)
  --allocations N      Independent paired allocations per point (default: 1)
  --launches N         Fresh fits per allocation (default: 3)
  --time HH:MM:SS      MPI/controller walltime (default: 02:00:00)
  --dry-run            Print the complete workflow without creating files or jobs

This is a spherical identity-grid pilot, not a production-grid publication run.
Strong scaling uses a fixed grid; weak scaling increases rows with node count.
The script runs the paper smoke suite, paired MPI timings, the opt-in two-host
Dask test, paired Dask timings, and the results notebook. Jobs run sequentially
and sbatch --wait keeps this command attached until they finish.
HELP
}

if [[ ${1:-} == --internal-dask ]]; then
    shift
    site=$1; output=$2; nodes=$3; fixture=$4; pair=$5; launches=$6; scale=$7
    mkdir -p "$output/cases"
    for engine in axis xesmf; do
        "$AXIS_PYTHON" - "$output/cases/$engine.json" "$engine" "$fixture" "$pair" "$scale" <<'PY'
import json, sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    "engine": sys.argv[2], "method": "conservative", "fixture": sys.argv[3],
    "comparison_pair_id": sys.argv[4], "scaling": sys.argv[5],
    "workload_id": "gaea-spherical-identity", "repetitions": 15,
    "warmups": 2, "reuse": [1, 10, 100],
}, indent=2) + "\n")
PY
        "$AXIS_PYTHON" "$benchmark" dask --site "$site" --case "$output/cases/$engine.json" \
            --output "$output/$engine" --jobs "$nodes" --launches "$launches" --live
    done
    exit
fi
if [[ ${1:-} == --internal-test ]]; then
    export AXIS_RUN_SLURM=1 AXIS_SLURM_PROFILE=$2 AXIS_SLURM_SHARED_DIR=$3
    exec "$AXIS_PYTHON" -m pytest -s "$repo/libs/axis/tests_python/test_axis_slurm_jobqueue.py"
fi

account= site= output= python_bin=python3 build= nodes=1,2 ranks_per_node=4 nx=128 ny=128 allocations=1 launches=3 walltime=02:00:00 dry_run=0
while (($#)); do
    case $1 in
        --help|-h) usage; exit ;;
        --dry-run) dry_run=1; shift ;;
        --account|--site|--output|--python|--build-dir|--nodes|--ranks-per-node|--nx|--ny|--allocations|--launches|--time)
            (($# >= 2)) || { echo "Missing value for $1" >&2; exit 2; }
            case $1 in
                --account) account=$2 ;; --site) site=$2 ;; --output) output=$2 ;;
                --python) python_bin=$2 ;; --build-dir) build=$2 ;; --nodes) nodes=$2 ;;
                --ranks-per-node) ranks_per_node=$2 ;; --nx) nx=$2 ;; --ny) ny=$2 ;;
                --allocations) allocations=$2 ;; --launches) launches=$2 ;; --time) walltime=$2 ;;
            esac
            shift 2 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done
[[ -n $account ]] || { echo "Provide --account PROJECT." >&2; exit 2; }
[[ $nodes =~ ^[1-9][0-9]*(,[1-9][0-9]*)*$ ]] || { echo "Invalid --nodes list." >&2; exit 2; }
for value in "$ranks_per_node" "$nx" "$ny" "$allocations" "$launches"; do
    [[ $value =~ ^[1-9][0-9]*$ ]] || { echo "Counts must be positive integers." >&2; exit 2; }
done
((nx >= 3 && ny >= 3)) || { echo "Grid dimensions must be at least 3." >&2; exit 2; }
[[ $walltime =~ ^[0-9]+:[0-5][0-9]:[0-5][0-9]$ ]] || { echo "Invalid --time." >&2; exit 2; }
IFS=, read -r -a node_counts <<< "$nodes"
for n in "${node_counts[@]}"; do
    ((ny >= n * ranks_per_node)) || { echo "ny must be at least nodes times ranks-per-node." >&2; exit 2; }
done
if [[ -z $output ]]; then
    output="${PWD}/axis-paper-$(date -u +%Y%m%dT%H%M%S)-$$"
fi
output=$(realpath -m "$output")
[[ ! -e $output ]] || { echo "Output already exists: $output" >&2; exit 2; }
if [[ $dry_run == 1 ]]; then
    printf 'Gaea C6 pilot\nOutput: %s\nNodes: %s\nRanks per node: %s\nGrid: %s x %s\nAllocations: %s\nLaunches: %s\n' \
        "$output" "$nodes" "$ranks_per_node" "$nx" "$ny" "$allocations" "$launches"
    printf '%s\n' 'Stages: build, paper smoke, MPI strong/weak, Dask strong/weak, Dask two-host test, notebook.'
    exit
fi
[[ -n $site && -f $site ]] || { echo "Provide --site with a configured Gaea JSON profile." >&2; exit 2; }
[[ -n ${ESMFMKFILE:-} && -f $ESMFMKFILE ]] || { echo "Set ESMFMKFILE to the installed ESMF esmf.mk." >&2; exit 2; }
for command in sbatch cmake git; do command -v "$command" >/dev/null || { echo "Missing $command." >&2; exit 2; }; done
python_bin=$(command -v "$python_bin")
site=$(realpath "$site")
"$python_bin" - "$site" "$account" "$ranks_per_node" <<'PY'
import json, sys
p=json.load(open(sys.argv[1]))
if p.get("account") != sys.argv[2] or p.get("cluster") != "c6" or p.get("queue") != "batch":
    raise SystemExit("Site account must match --account, cluster must be c6, and queue must be batch.")
if p.get("cores") != int(sys.argv[3]) or p.get("processes") != int(sys.argv[3]):
    raise SystemExit("Site cores and processes must both match --ranks-per-node.")
for key in ("interface", "scheduler_interface", "local_directory"):
    if not p.get(key) or "REPLACE" in p[key]:
        raise SystemExit(f"Set {key} in the site profile.")
for module in ("numpy", "xarray", "netCDF4", "dask", "distributed", "dask_jobqueue", "xesmf", "ESMF", "axis", "nbconvert", "ipykernel", "pytest"):
    __import__(module)
PY
mkdir "$output"
build=${build:-$output/build}
mkdir -p "$output/results" "$output/logs" "$output/fixtures" "$output/cases"
cp "$site" "$output/site.json"
site="$output/site.json"
export AXIS_REPO="$repo" AXIS_BUILD="$build" AXIS_RESULTS="$output/results" AXIS_PYTHON="$python_bin" AXIS_LAUNCHES="$launches"
printf '%s\n' "$repo" > "$output/repository.txt"
git -C "$repo" rev-parse HEAD > "$output/revision.txt"
git -C "$repo" status --short > "$output/working-tree.txt"
cmake -S "$repo/libs/axis" -B "$build" -DCMAKE_BUILD_TYPE=Release \
    -DAXIS_BUILD_PAPER=ON -DAXIS_PAPER_ENABLE_ESMF=ON -DAXIS_BUILD_BENCHMARKS=ON -DHALO_BUILD_FORTRAN=OFF
cmake --build "$build" --parallel "${AXIS_BUILD_JOBS:-8}"

submit=(sbatch --wait --clusters=c6 --account="$account" --partition=batch --exclusive --time="$walltime")
batch="$paper/scripts/axis-paper-scale.sbatch"
smoke="$paper/config/smoke-matched.json"
"$python_bin" "$paper/scripts/prepare_cases.py" --profile "$smoke" --output "$output/smoke-cases"
"${submit[@]}" --nodes=1 --ntasks=1 --cpus-per-task=1 --output="$output/logs/paper-%j.log" \
    "$batch" paper "$smoke" "$output/smoke-cases"

for scale in strong weak; do
    for n in "${node_counts[@]}"; do
        ranks=$((n * ranks_per_node))
        rows=$ny
        [[ $scale == strong ]] || rows=$((ny * n))
        fixture="$output/fixtures/$scale-$n"
        "$python_bin" "$benchmark" fixture tiny --output "$fixture" --ranks "$ranks" --nx "$nx" --ny "$rows"
        for engine in axis esmf; do
            "$python_bin" - "$output/cases/$scale-$n-$engine.json" "$engine" "$fixture/manifest.json" "$scale" <<'PY'
import json, sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    "engine": sys.argv[2], "method": "conservative", "fixture": sys.argv[3],
    "scaling": sys.argv[4], "workload_id": "gaea-spherical-identity",
    "repetitions": 15, "warmups": 2, "reuse": [1, 10, 100],
}, indent=2) + "\n")
PY
        done
        for ((repeat=1; repeat<=allocations; repeat++)); do
            "${submit[@]}" --nodes="$n" --ntasks="$ranks" --ntasks-per-node="$ranks_per_node" \
                --cpus-per-task=1 --hint=nomultithread --output="$output/logs/mpi-$scale-$n-$repeat-%j.log" \
                "$batch" matched "$site" "$output/cases/$scale-$n-axis.json" "$output/cases/$scale-$n-esmf.json"
        done
    done
done

# The scheduler runs on a dedicated allocated controller; workers use their own
# exclusive jobs through dask-jobqueue. Allow enough time for queue delays.
for scale in strong weak; do
    for n in "${node_counts[@]}"; do
        fixture="$output/fixtures/$scale-$n/manifest.json"
        for ((repeat=1; repeat<=allocations; repeat++)); do
            pair="dask-$scale-$n-$repeat"
            "${submit[@]}" --nodes=1 --ntasks=1 --cpus-per-task=1 \
                --output="$output/logs/$pair-%j.log" "$script_dir/run-gaea-paper.sh" \
                --internal-dask "$site" "$output/results/$pair" "$n" "$fixture" "$pair" "$launches" "$scale"
        done
    done
done

# A separate two-host worker test verifies actual host placement and cleanup.
"${submit[@]}" --nodes=1 --ntasks=1 --cpus-per-task=1 --output="$output/logs/dask-test-%j.log" \
    "$script_dir/run-gaea-paper.sh" --internal-test "$site" "$output/results"

export AXIS_PAPER_DIR="$paper" AXIS_BENCHMARK_RESULTS="$output/results" AXIS_BENCHMARK_EXPORTS="$output/plots"
export MPLBACKEND=Agg
"$python_bin" -m jupyter nbconvert --to notebook --execute --ExecutePreprocessor.timeout=600 \
    --output "$output/axis-scaling-executed.ipynb" "$paper/notebooks/axis_scaling.ipynb"
printf '\nResults: %s\nNotebook: %s\n' "$output/results" "$output/axis-scaling-executed.ipynb"
