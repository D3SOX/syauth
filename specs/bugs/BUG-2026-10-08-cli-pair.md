# Pair command missing from CLI dispatcher

Running the README's `syauth pair` command against the current source build
returns `error: unrecognized subcommand 'pair'` with exit status 2. The
`Cmd` enum and dispatcher omit pairing, while `PairOpts`, `BluerPairBackend`,
and the pairing flow remain implemented in the CLI library.

Restore the command and dispatch it to that existing implementation. Keep
the adapter, numeric-comparison, and app-level OOB checks intact. Stdio
handles must remain unlocked while awaiting the BlueZ callback because
the callback also reads and writes stdio from a blocking worker.

Regression coverage exercises `pair --help` through the executable. Real
BLE pairing on Nico's laptop and Pixel checks the integrated flow.
