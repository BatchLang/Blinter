# SSOT Audit Report

## ERROR (0)

_None_

## WARNING (2)

- **[reference-matrix]** SETLOCAL/ENDLOCAL pairing and nesting limit: corpus integration/p024-conditional-setlocal does not assert any of ['P005', 'P006', 'P027']
- **[reference-matrix]** FOR /F tokenization, delimiters, and CSV: corpus syntax/for-f-delims-only-valid does not assert any of ['E037', 'E038', 'W034', 'W035', 'W037', 'W048', 'W063']

## INFO (3)

- **[commands]** dpath is both builtin and deprecated (intentional for W024 recognition)
- **[commands]** keys is both builtin and deprecated (intentional for W024 recognition)
- **[commands]** wmic is both builtin and deprecated (intentional for W024 recognition)
