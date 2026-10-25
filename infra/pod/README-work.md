# /work on the shared render pod

> **Reusing this tooling on a rented machine:** it predates lesson 247 and has no host-side cap and
> no continuous copy-off. Before any reuse, start a detached timer on the host that deletes it at the
> cap as the very first command (before `setup.sh`'s apt), and copy each finished clip off every
> couple of minutes from the start; state both in the plan (lesson 247, docs/PLAN.md risks).

This was a CPU pod (32 vCPU, 64 GB) for the dry run; the dataset itself was rendered on a GPU pod
(see docs/eval/dataset-v2-freeze.json). It is rented by Kian and deleted when the work is done. **No secrets
here:** no keys, SAS links, `.env` files or tokens. Clone the public repo over https, and copy results
back over SSH to your own machine.

Each session works in its own folder, `/work/<session-name>/`, with its own clone and outputs. Don't
touch other folders. `/work/render` belongs to the dataset render (#194).

Every job that uses more than one core runs through `/work/bin/reserve <cores> <session-name>
<command…>`, sized to what the job uses: a 20-match sweep with 8 workers reserves 8. The budget is 30
of 32 cores in total, and at most 24 for engine work while the render is idle. `/work/bin/cores`
shows who holds what. When the final render starts, `/work/cores/RENDER-EXCLUSIVE` appears: no new
engine job starts, and the sessions are asked to stop the running ones. Long jobs belong in
`tmux new -s <session-name>`, so a dropped SSH connection doesn't kill them.
