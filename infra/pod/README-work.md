# /work on the shared render pod

This is a CPU pod (32 vCPU, 64 GB), rented by Kian and deleted when the work is done. **No secrets
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
