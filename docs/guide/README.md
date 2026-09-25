# Guides

The guides use small, complete projects. Each example starts with a YAML file,
adds a Python script, and shows the behavior to verify.

1. [Edit a service configuration](./quickstart.md) - update one setting while
   preserving comments and layout.
2. [Build a release metadata command](./round-trips.md) - use the document API
   to update values and add a comment with an explicit style.
3. [Validate a CI manifest safely](./safety.md) - read untrusted YAML without
   constructing application-specific objects.

The examples use only Python and `pythonizeyaml`; no framework is required.
