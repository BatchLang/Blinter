# SSOT Audit Report

## ERROR (0)

_None_

## WARNING (27)

- **[reference-matrix]** Nested parentheses and block structure: corpus syntax/e001-for-f-in-quoted-valid does not assert any of ['E001']
- **[reference-matrix]** IF command format and EXIST/NOT mixing: corpus syntax/e003-if-trailing-assign-valid does not assert any of ['E003', 'E004', 'E036', 'E039', 'W021', 'W056']
- **[reference-matrix]** Unreachable code after EXIT/GOTO: corpus integration/e008-exit-in-conditional-block-valid does not assert any of ['E008']
- **[reference-matrix]** Percent-tilde (%~) parameter expansion: corpus syntax/e019-set-a-percent-tilde-params-valid does not assert any of ['E017', 'E019', 'E024', 'E025', 'W051']
- **[reference-matrix]** Percent-tilde (%~) parameter expansion: corpus syntax/e019-for-loop-tilde-z-valid does not assert any of ['E017', 'E019', 'E024', 'E025', 'W051']
- **[reference-matrix]** Percent-tilde (%~) parameter expansion: corpus syntax/e019-percent-tilde-dp0-adjacent-valid does not assert any of ['E017', 'E019', 'E024', 'E025', 'W051']
- **[reference-matrix]** Percent-tilde (%~) parameter expansion: corpus syntax/e019-for-metavar-bare-tilde-valid does not assert any of ['E017', 'E019', 'E024', 'E025', 'W051']
- **[reference-matrix]** Percent-tilde (%~) parameter expansion: corpus syntax/e019-for-metavar-adjacent-literal-valid does not assert any of ['E017', 'E019', 'E024', 'E025', 'W051']
- **[reference-matrix]** SETLOCAL/ENDLOCAL pairing and nesting limit: corpus integration/p006-subroutine-exit-valid does not assert any of ['P005', 'P006', 'P027']
- **[reference-matrix]** SETLOCAL/ENDLOCAL pairing and nesting limit: corpus integration/p006-main-exit-b-valid does not assert any of ['P005', 'P006', 'P027']
- **[reference-matrix]** SETLOCAL/ENDLOCAL pairing and nesting limit: corpus integration/p024-conditional-setlocal does not assert any of ['P005', 'P006', 'P027']
- **[reference-matrix]** FOR loop and I/O performance anti-patterns: corpus syntax/p022-redir-after-loop-valid does not assert any of ['P009', 'P010', 'P013', 'P014', 'P015', 'P016', 'P018', 'P019', 'P020', 'P021', 'P022', 'P023', 'P025']
- **[reference-matrix]** FOR loop and I/O performance anti-patterns: corpus syntax/p023-seta-after-loop-valid does not assert any of ['P009', 'P010', 'P013', 'P014', 'P015', 'P016', 'P018', 'P019', 'P020', 'P021', 'P022', 'P023', 'P025']
- **[reference-matrix]** FOR loop and I/O performance anti-patterns: corpus syntax/w048-for-f-csv does not assert any of ['P009', 'P010', 'P013', 'P014', 'P015', 'P016', 'P018', 'P019', 'P020', 'P021', 'P022', 'P023', 'P025']
- **[reference-matrix]** Global style conventions and readability: corpus syntax/s028-paren-required-chain does not assert any of ['S001', 'S002', 'S003', 'S004', 'S007', 'S008', 'S009', 'S011', 'S012', 'S013', 'S014', 'S015', 'S017', 'S018', 'S019', 'S020', 'S022', 'S023', 'S024', 'S026', 'S027', 'S028']
- **[reference-matrix]** Compatibility, portability, and environment warnings: corpus syntax/w014-setp-from-file-valid does not assert any of ['W002', 'W003', 'W004', 'W005', 'W006', 'W007', 'W008', 'W009', 'W010', 'W011', 'W012', 'W014', 'W020', 'W026', 'W027', 'W028', 'W030', 'W031', 'W032', 'W033', 'W042', 'W043', 'W060']
- **[reference-matrix]** Compatibility, portability, and environment warnings: corpus syntax/w048-for-f-csv does not assert any of ['W002', 'W003', 'W004', 'W005', 'W006', 'W007', 'W008', 'W009', 'W010', 'W011', 'W012', 'W014', 'W020', 'W026', 'W027', 'W028', 'W030', 'W031', 'W032', 'W033', 'W042', 'W043', 'W060']
- **[reference-matrix]** Compatibility, portability, and environment warnings: corpus integration/w004-goto-exit-handler does not assert any of ['W002', 'W003', 'W004', 'W005', 'W006', 'W007', 'W008', 'W009', 'W010', 'W011', 'W012', 'W014', 'W020', 'W026', 'W027', 'W028', 'W030', 'W031', 'W032', 'W033', 'W042', 'W043', 'W060']
- **[reference-matrix]** Compatibility, portability, and environment warnings: corpus integration/w004-shift-parse-valid does not assert any of ['W002', 'W003', 'W004', 'W005', 'W006', 'W007', 'W008', 'W009', 'W010', 'W011', 'W012', 'W014', 'W020', 'W026', 'W027', 'W028', 'W030', 'W031', 'W032', 'W033', 'W042', 'W043', 'W060']
- **[reference-matrix]** Compatibility, portability, and environment warnings: corpus integration/s015-inconsistent-goto-colon does not assert any of ['W002', 'W003', 'W004', 'W005', 'W006', 'W007', 'W008', 'W009', 'W010', 'W011', 'W012', 'W014', 'W020', 'W026', 'W027', 'W028', 'W030', 'W031', 'W032', 'W033', 'W042', 'W043', 'W060']
- **[reference-matrix]** Compatibility, portability, and environment warnings: corpus integration/unreachable-goto-flow does not assert any of ['W002', 'W003', 'W004', 'W005', 'W006', 'W007', 'W008', 'W009', 'W010', 'W011', 'W012', 'W014', 'W020', 'W026', 'W027', 'W028', 'W030', 'W031', 'W032', 'W033', 'W042', 'W043', 'W060']
- **[reference-matrix]** Compatibility, portability, and environment warnings: corpus syntax/w019-goto-lf does not assert any of ['W002', 'W003', 'W004', 'W005', 'W006', 'W007', 'W008', 'W009', 'W010', 'W011', 'W012', 'W014', 'W020', 'W026', 'W027', 'W028', 'W030', 'W031', 'W032', 'W033', 'W042', 'W043', 'W060']
- **[reference-matrix]** Compatibility, portability, and environment warnings: corpus integration/w043-tasklist-before-taskkill does not assert any of ['W002', 'W003', 'W004', 'W005', 'W006', 'W007', 'W008', 'W009', 'W010', 'W011', 'W012', 'W014', 'W020', 'W026', 'W027', 'W028', 'W030', 'W031', 'W032', 'W033', 'W042', 'W043', 'W060']
- **[reference-matrix]** FOR /F tokenization, delimiters, and CSV: corpus syntax/e038-for-f-skip-variable-valid does not assert any of ['E037', 'E038', 'W034', 'W035', 'W037', 'W048', 'W063']
- **[reference-matrix]** FOR /F tokenization, delimiters, and CSV: corpus syntax/e038-for-f-tokens-delims-valid does not assert any of ['E037', 'E038', 'W034', 'W035', 'W037', 'W048', 'W063']
- **[reference-matrix]** FOR /F tokenization, delimiters, and CSV: corpus syntax/for-f-delims-only-valid does not assert any of ['E037', 'E038', 'W034', 'W035', 'W037', 'W048', 'W063']
- **[reference-matrix]** Security: injection, credentials, and dangerous commands: corpus integration/sec013-installer-redirection-valid does not assert any of ['SEC001', 'SEC002', 'SEC003', 'SEC004', 'SEC005', 'SEC008', 'SEC009', 'SEC010', 'SEC011', 'SEC013', 'SEC014', 'SEC015']

## INFO (3)

- **[commands]** dpath is both builtin and deprecated (intentional for W024 recognition)
- **[commands]** keys is both builtin and deprecated (intentional for W024 recognition)
- **[commands]** wmic is both builtin and deprecated (intentional for W024 recognition)
