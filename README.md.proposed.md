# syauth

<img src="assets/syauth.png" width="160" alt="syauth pixel cat paw holding a gold key">

Approve Linux PAM authentication on your Android phone with a fresh strong biometric. The desktop daemon sends a Bluetooth challenge, verifies the phone's Ed25519 signature, and returns the result to the service's PAM stack.

## Documentation

Start with the [documentation home](docs/index.md), then follow [installation](docs/how-to/install.md), [pairing](docs/how-to/pair-and-revoke.md), and [your first approval](docs/tutorials/first-unlock.md).

The [mechanics guide](docs/explanation/mechanics.md) explains pairing, discovery, and unlock, with interactive animations in the MkDocs site. Read the [security boundaries](docs/explanation/security.md) for the differences between the active implementation and the design specification.

Preview the styled documentation locally:

```sh
python3 -m venv target/docs-venv
target/docs-venv/bin/python -m pip install -r requirements-docs.txt
target/docs-venv/bin/python -m mkdocs serve
```

## Requirements

Linux with PAM, BlueZ, a BLE advertising adapter, and a systemd user session; Android 13 or later with a supported Ed25519 Android Keystore and an enrolled strong biometric. Being nearby prepares the connection; each authentication still requires approval.

## Development

```sh
make build
make test
make lint
```

See [documentation development](docs/contributing/documentation.md) for site checks. The Rust workspace lives under `crates/`; the companion app lives under `syauth-android/`. Product design and roadmap documents live under `specs/`.

## License

[MIT](LICENSE). Maintained by [dmytrogajewski](https://github.com/dmytrogajewski) and contributors.
