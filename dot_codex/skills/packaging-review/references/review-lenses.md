# Authoritative Python packaging specifications

Consult the primary specification or tool documentation that owns the
affected behavior. These sources are public, maintainer-neutral evidence;
project history or a private reviewer profile is a separate, optional input.

## Declarations, extras, and dependency groups

- Pyproject metadata:
  https://packaging.python.org/en/latest/specifications/pyproject-toml/.
- Dependency specifiers and environment markers:
  https://packaging.python.org/en/latest/specifications/dependency-specifiers/.
- Dependency groups:
  https://packaging.python.org/en/latest/specifications/dependency-groups/.
- Declaring project dependencies:
  https://docs.astral.sh/uv/concepts/projects/dependencies/.

## Resolution and distribution

- Resolver behavior:
  https://pip.pypa.io/en/stable/topics/dependency-resolution/.
- Source-distribution format:
  https://packaging.python.org/en/latest/specifications/source-distribution-format/.
- Binary-distribution format:
  https://packaging.python.org/en/latest/specifications/binary-distribution-format/.
- Platform compatibility tags:
  https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/.

Use the specification that actually governs the observed problem; do not
treat a related tool, an incident discussion, or a successful retry as a
substitute for the affected package's producer and consumer.
