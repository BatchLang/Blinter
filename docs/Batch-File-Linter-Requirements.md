# Batch File Linter Requirements

## Rule Categories Summary

<!-- GENERATED:rule-catalog:start -->

### Error Level Rules (E001-E999)
**Auto-generated from spec/data/rules.yaml**

- **E001**: Nested parentheses mismatch
- **E002**: Missing label for GOTO statement
- **E003**: IF statement improper formatting
- **E004**: IF EXIST syntax mixing
- **E005**: Invalid path syntax
- **E006**: Potentially undefined variable reference (Warning severity despite E-prefix)
- **E007**: Empty variable check syntax error
- **E008**: Unreachable code after EXIT or GOTO
- **E009**: Mismatched quotes
- **E010**: Malformed FOR loop missing DO
- **E011**: Invalid variable expansion syntax
- **E012**: Missing CALL for subroutine invocation
- **E013**: Invalid command syntax detected
- **E014**: Missing colon in CALL statement
- **E015**: Missing colon in GOTO :EOF statement
- **E016**: Invalid errorlevel comparison syntax
- **E017**: Invalid percent-tilde syntax
- **E018**: Unix line endings detected
- **E019**: Percent-tilde on non-parameter variable
- **E020**: Invalid FOR loop variable syntax
- **E021**: Invalid string operation syntax
- **E022**: Invalid arithmetic expression in SET /A
- **E023**: Missing quotes in SET /A with special characters
- **E024**: Invalid parameter modifier combination
- **E025**: Parameter modifier on wrong context
- **E027**: UNC path used as working directory
- **E028**: Complex quote escaping error
- **E029**: Complex SET /A expression errors
- **E030**: Improper caret escape sequence
- **E031**: Invalid multilevel escaping
- **E032**: Continuation character with trailing spaces
- **E033**: Double percent escaping error
- **E034**: Removed Windows command detected
- **E035**: Smart quote characters in batch source
- **E036**: IF EXISTS typo
- **E037**: FOR /F eol option has multiple characters
- **E038**: FOR /F invalid skip or tokens suboption
- **E039**: IF block parenthesis must be on same line
- **E040**: FOR block parenthesis must be on same line as DO
- **E041**: SET /P missing variable assignment
- **E042**: Text after closing parenthesis in block
- **E043**: Double-colon comment inside parenthesized block
- **E044**: ELSE on a new line
- **E045**: Invalid internal command switch or argument
- **E046**: Malformed stream redirection
- **E047**: Unescaped specials in FOR /F command or ECHO in a block
- **E048**: Line exceeds maximum length
### Warning Level Rules (W001-W999)
**Auto-generated from spec/data/rules.yaml**

- **W001**: Missing exit code
- **W002**: Missing ERRORLEVEL check
- **W003**: Operation without error handling
- **W004**: Potential infinite loop
- **W005**: Unquoted variable with spaces
- **W006**: Network operation without timeout
- **W007**: File operation on potentially locked file
- **W008**: Permanent PATH modification
- **W009**: Windows version compatibility
- **W010**: Architecture-specific operation
- **W011**: Unicode handling issue
- **W012**: Non-ASCII characters detected
- **W013**: Duplicate label
- **W014**: Missing PAUSE for user interaction
- **W017**: Errorlevel comparison semantic difference
- **W018**: Multi-byte characters with potential line ending risks
- **W019**: GOTO/CALL with potential line ending risks
- **W020**: FOR loop missing /F options for complex parsing
- **W021**: IF comparison without quotes
- **W022**: Missing SETLOCAL EnableDelayedExpansion
- **W023**: Inefficient nested FOR loops
- **W024**: Deprecated command detected
- **W025**: Missing error handling
- **W026**: Inefficient parameter modifier usage
- **W027**: Command behavior differs between interpreters
- **W028**: Errorlevel handling difference between .bat/.cmd
- **W029**: 16-bit command in 64-bit context
- **W030**: Non-ASCII characters may cause encoding issues
- **W031**: Unicode filename in batch operation
- **W032**: Missing character set declaration
- **W033**: Command execution may be ambiguous
- **W034**: FOR /F missing usebackq option
- **W035**: FOR /F tokenizing without proper delimiters
- **W036**: FOR /F missing skip option for headers
- **W037**: FOR /F missing eol option for comments
- **W038**: FOR /R with literal filename
- **W039**: Nested FOR loops without call optimization
- **W040**: Nested FOR loop variable reuse
- **W042**: Timeout command without /NOBREAK option
- **W043**: Process management without proper verification
- **W044**: SET command spacing around equals
- **W045**: SET /A leading zero octal literal
- **W046**: Unquoted IF numeric comparison ambiguity
- **W047**: Substring expansion on empty variable
- **W048**: FOR /F may skip empty delimited fields
- **W049**: Assignment to pseudo-environment variable
- **W050**: Invalid SHIFT /n switch value
- **W051**: Ambiguous double-digit batch parameter
- **W052**: SHIFT inside parenthesized block
- **W053**: Bare SHIFT changes script name parameter
- **W054**: Digit-prefixed variable name
- **W055**: IF DEFINED with percent-wrapped variable
- **W056**: IF clause with pseudo AND/OR operator
- **W057**: Batch file invoked without CALL
- **W058**: REN destination includes a path
- **W059**: FOR loop variable case mismatch
- **W060**: SETX uses equals sign instead of space
- **W061**: Unbalanced PUSHD and POPD commands
- **W062**: CD without /D for cross-drive path
- **W063**: FOR /F loop variable beyond tokens range
- **W064**: ALLUSERPROFILE environment-variable typo
- **W065**: Wildcard in IF string comparison
- **W066**: 2>&1 not at the end of the command
- **W067**: SET of a system environment variable
- **W068**: Percent expansion of a variable set in the same parenthesized block
- **W069**: TIME expansion without replacing the leading space
- **W070**: SET PATH or PROMPT chained with AND in a .bat file
- **W071**: Parse-time pseudo-variable inside a parenthesized block
### Style Level Rules (S001-S999)
**Auto-generated from spec/data/rules.yaml**

- **S001**: Missing @ECHO OFF at file start
- **S002**: ECHO OFF without @ prefix
- **S003**: Inconsistent command capitalization
- **S004**: Trailing whitespace
- **S005**: Mixed line endings
- **S007**: BAT extension used instead of CMD for newer Windows
- **S008**: Missing comments for complex code
- **S009**: Magic numbers used
- **S010**: Dead code detected
- **S011**: Line exceeds maximum length
- **S012**: Inconsistent indentation
- **S013**: Missing file header documentation
- **S014**: Long parameter list affects readability
- **S015**: Inconsistent colon usage in GOTO statements
- **S016**: Potentially unsafe double-colon comment
- **S017**: Inconsistent variable naming convention
- **S018**: Missing subroutine documentation
- **S019**: Magic numbers in code
- **S020**: Long line without continuation
- **S022**: Inconsistent variable naming convention
- **S023**: Magic timeout values without explanation
- **S024**: Complex one-liner should be split
- **S026**: Inconsistent continuation character usage
- **S027**: Missing blank lines around code blocks
- **S028**: Redundant parentheses in simple commands
- **S029**: @ prefix after the first line
- **S030**: Redundant colon on device name
### Security Level Rules (SEC001+)
**Auto-generated from spec/data/rules.yaml**

- **SEC001**: Potential command injection vulnerability
- **SEC002**: Unsafe SET command usage
- **SEC003**: Dangerous command without confirmation
- **SEC004**: Dangerous registry operation
- **SEC005**: Missing privilege check
- **SEC006**: Hardcoded absolute path (Style severity despite SEC-prefix)
- **SEC007**: Hardcoded temporary directory
- **SEC008**: Plain text credentials detected
- **SEC009**: PowerShell execution policy bypass
- **SEC010**: Sensitive information in ECHO output
- **SEC011**: Unvalidated path traversal
- **SEC012**: Unsafe temporary file creation
- **SEC013**: Command injection via variable substitution
- **SEC014**: Unescaped user input in command execution
- **SEC015**: Process killing without authentication
- **SEC016**: Automatic restart without failure limits
- **SEC017**: Temporary file creation in predictable location
- **SEC018**: Command output redirection to insecure location
- **SEC019**: Batch self-modification vulnerability
- **SEC020**: UNC path without UAC elevation check
- **SEC021**: Fork bomb pattern detected
- **SEC022**: Potential hosts file modification
- **SEC023**: Autorun.inf creation detected
- **SEC024**: Batch file copying itself to removable media
- **SEC025**: Unquoted current-directory expansion
### Performance Level Rules (P001-P999)
**Auto-generated from spec/data/rules.yaml**

- **P001**: Redundant file existence check
- **P002**: Code duplication detected
- **P003**: Unnecessary SETLOCAL
- **P004**: Unnecessary ENABLEDELAYEDEXPANSION
- **P005**: ENDLOCAL without SETLOCAL
- **P006**: Missing ENDLOCAL before exit
- **P007**: Temporary file without random name
- **P008**: Delayed expansion without enablement
- **P009**: Inefficient FOR loop pattern
- **P010**: DIR without /B when output is processed
- **P012**: Inefficient string operations
- **P013**: Missing /B flag for large DIR operations
- **P014**: Unnecessary command output
- **P015**: Inefficient delay implementation
- **P016**: Inefficient string concatenation in loops
- **P017**: Repeated file existence checks
- **P018**: Inefficient directory traversal
- **P019**: Excessive variable expansion in loops
- **P020**: Redundant command echoing suppression
- **P021**: Inefficient process checking pattern
- **P022**: Unnecessary output redirection in loops
- **P023**: Inefficient arithmetic operations
- **P024**: Redundant SETLOCAL/ENDLOCAL pairs
- **P025**: Inefficient wildcard usage in file operations
- **P026**: Redundant DISABLEDELAYEDEXPANSION
- **P027**: SETLOCAL nesting exceeds recommended depth

<!-- GENERATED:rule-catalog:end -->

**Blinter** provides comprehensive static analysis with **built-in rules** registered in `blinter.rules.registry` (currently **193** rules; see `RULE_COUNT` in that module). Rule IDs may have gaps where rules were retired or consolidated (for example W041, S025, P011).

Across 5 severity levels:

> **Security rules:** SEC-prefixed findings are static heuristics over source text. They help spot risky patterns but do not prove exploitability or guarantee runtime safety.

## Implementation Guidelines
*Each rule should provide clear explanations and actionable recommendations*

### Output Format
- **Line number**: Specify exact line where issue occurs
- **Rule code**: Unique identifier (e.g., E001, W001, S001, P001)
- **Explanation**: Clear description of why this is an issue
- **Recommendation**: Specific guidance on how to fix the problem
- **Severity level**: Error, Warning, Style, Security, or Performance

### Example Output Structure
```text
Line 5: Missing '@ECHO OFF' at top of file (S001)
- Explanation: Batch scripts usually start with '@ECHO OFF' to prevent command echoing during execution
- Recommendation: Add '@ECHO OFF' as the first line of your script
```

## Error Level Rules
*Issues that will cause the script to fail or behave incorrectly*

### Syntax Errors
- **Nested parentheses**: Error on improper nesting and matching of parentheses
  ```batch
  # Bad
  if exist "file.txt" (
      echo Found file
  # Missing closing parenthesis
  
  # Good
  if exist "file.txt" (
      echo Found file
  )
  ```

- **Missing labels**: Error on `GOTO` statements pointing to non-existent labels
  ```batch
  # Bad
  GOTO nonexistent_label
  
  # Good
  GOTO end
  :end
  ```

- **IF statement formatting**: Error on improper spacing and syntax in conditional statements
  ```batch
  # Bad
  IF"%VAR%"=="value"ECHO Match
  
  # Good
  IF "%VAR%"=="value" ECHO Match
  ```

- **IF EXIST vs comparison**: Error when mixing IF EXIST and comparison syntax
  ```batch
  # Bad
  IF EXIST file.txt == true ECHO Found
  IF %FILE_EXISTS% EXIST ECHO Invalid
  
  # Good
  IF EXIST file.txt ECHO Found
  IF "%FILE_EXISTS%"=="true" ECHO Found
  ```

- **Path validation**: Error on invalid path syntax and paths exceeding length limits
  ```batch
  # Bad
  COPY "C:\invalid<>path\file.txt" dest
  
  # Good
  COPY "C:\valid\path\file.txt" dest
  ```

### Variable Errors
- **Undefined variables**: Error on references to variables that were never set
  ```batch
  # Bad
  ECHO %UNDEFINED_VAR%
  
  # Good
  SET MY_VAR=value
  ECHO %MY_VAR%
  ```

- **Empty variable checks**: Error on incorrect syntax for checking if variables are empty
  ```batch
  # Bad
  IF %VAR%=="" ECHO Empty
  
  # Good
  IF "%VAR%"=="" ECHO Empty
  ```

- **Invalid errorlevel syntax**: Error on improper errorlevel comparison syntax that will cause script failure
  ```batch
  # Bad - Missing comparison operator
  IF NOT %ERRORLEVEL% 1 (
      ECHO This syntax is invalid and causes errors
  )
  
  # Good - Correct ERRORLEVEL keyword usage
  IF NOT ERRORLEVEL 1 (
      ECHO This is the correct syntax
  )
  
  # Good - Explicit variable comparison
  IF %ERRORLEVEL% NEQ 1 (
      ECHO This explicit comparison works correctly
  )
  ```

### Line Ending Issues
- **Unix line endings**: Critical error that can cause GOTO/CALL failures due to Windows batch parser bugs
  ```batch
  # Bad - Unix line endings (LF-only) cause parser failures
  @echo off\n
  goto :main\n
  :main\n
  echo Hello\n
  
  # Good - Windows line endings (CRLF)
  @echo off\r\n
  goto :main\r\n
  :main\r\n
  echo Hello\r\n
  ```

### Advanced Variable Expansion Errors
- **Percent-tilde syntax validation**: Error on malformed %~modifiers
  ```batch
  # Bad - Invalid modifier
  echo %~q1%
  
  # Good - Valid modifiers
  echo %~n1  :: filename
  echo %~f1  :: full path
  echo %~d1  :: drive letter
  echo %~p1  :: path
  echo %~x1  :: extension
  ```

- **Percent-tilde parameter validation**: Error when used on non-parameter variables
  ```batch
  # Bad - Can't use on regular variables
  echo %~nMYVAR%
  
  # Good - Only on parameters and FOR variables
  echo %~n1
  echo %~f%%i  :: in FOR loop
  ```

- **FOR loop variable syntax**: Error on incorrect %/% usage in batch files
  ```batch
  # Bad - Single % in batch files
  for %i in (*.txt) do echo %i
  
  # Good - Double %% in batch files
  for %%i in (*.txt) do echo %%i
  ```

- **String operation syntax**: Error on malformed substring/replacement operations
  ```batch
  # Bad - Missing parameters
  echo %var:~%
  
  # Good - Proper syntax
  echo %var:~0,5%        :: substring
  echo %var:old=new%     :: replacement
  ```

- **SET /A arithmetic**: Error on invalid expressions or unquoted special characters
  ```batch
  # Bad - Unquoted special characters
  set /a result=5^2
  
  # Good - Quoted special characters
  set /a "result=5^2"
  set /a "result=(5+3)*2"
  ```

### Control Flow Errors
- **Unreachable code**: Error on code after `EXIT` or `GOTO` statements
  ```batch
  # Bad
  EXIT /b 0
  ECHO This will never execute
  
  # Good
  ECHO This executes
  EXIT /b 0
  ```

### Removed Commands
- **E034: Removed Windows command detected**: Commands completely removed from Windows
  ```batch
  # Bad - These commands have been removed from Windows
  CASPOL -m -ag 1 -url file://c:\temp\* FullTrust
  DISKCOMP A: B:
  APPEND C:\DATA
  BROWSTAT status
  INUSE file.dll /Y
  NET PRINT \\server\printer file.txt
  DISKCOPY A: B:
  STREAMS -s file.txt
  
  # Good - Use modern alternatives
  # Instead of CASPOL: Use Code Access Security Policy Tool from SDK
  # Instead of DISKCOMP: Use FC for file comparison
  FC /B file1.txt file2.txt
  # Instead of APPEND: Modify PATH or use full paths
  SET "PATH=%PATH%;C:\DATA"
  # Instead of BROWSTAT: Use NET VIEW or PowerShell
  NET VIEW \\computer
  # Instead of INUSE: Use HANDLE.EXE from Sysinternals
  # Instead of NET PRINT: Use PowerShell Print cmdlets
  Get-Printer | Format-Table
  # Instead of DISKCOPY: Use ROBOCOPY or XCOPY
  ROBOCOPY source dest /E
  # Instead of STREAMS: Use Get-Item -Stream in PowerShell
  powershell -Command "Get-Item file.txt -Stream *"
  ```

## Warning Level Rules
*Issues that are bad practice but won't necessarily break the script*

### Missing Error Handling
- **Exit codes (W001)**: Warn when scripts can reach end-of-file without an explicit EXIT statement
  
  The linter performs intelligent control flow analysis to detect if the main execution path can fall through to EOF without encountering an EXIT statement. This rule uses smart detection logic that:
  
  - **Flags**: Scripts where main execution can reach EOF without EXIT
  - **Flags**: Scripts relying on implicit exit (using the last command's exit code)
  - **Allows**: Scripts where all execution paths lead to EXIT or GOTO :EOF
  - **Allows**: Pure subroutine libraries (scripts starting with a label before any executable code)
  - **Allows**: Scripts with only @ECHO OFF and comments (setup-only scripts)
  - **Understands**: GOTO statements, labels, and conditional branches
  
  ```batch
  # Bad - Can reach EOF without EXIT
  @echo off
  echo Starting script
  echo Doing some work
  # Script ends without EXIT - relies on implicit exit
  
  # Bad - One branch can reach EOF
  @echo off
  IF "%1"=="test" (
      echo Test mode
      EXIT /b 0
  )
  echo Continuing after IF
  # Falls through to EOF if not in test mode
  
  # Good - Explicit EXIT at end
  @echo off
  COPY file1.txt file2.txt
  IF ERRORLEVEL 1 EXIT /b 1
  EXIT /b 0
  
  # Good - GOTO :EOF is equivalent to EXIT
  @echo off
  echo Starting script
  echo Doing work
  GOTO :EOF
  
  # Good - Main code jumps to label with EXIT
  @echo off
  echo Starting
  GOTO end
  :end
  echo Ending
  EXIT /b 0
  
  # Good - Subroutine library (label before any code)
  @echo off
  GOTO :EOF
  
  :subroutine1
  echo In subroutine 1
  GOTO :EOF
  
  :subroutine2
  echo In subroutine 2
  GOTO :EOF
  
  # Good - Main code then subroutines with EXIT before subroutines
  @echo off
  echo Main script execution
  echo Doing main work
  GOTO :EOF
  
  :subroutine
  echo This is a subroutine
  GOTO :EOF
  ```

- **Error checking**: Suggest checking `%ERRORLEVEL%` after critical operations
  ```batch
  # Bad
  DEL important_file.txt
  ECHO File deleted
  
  # Good
  DEL important_file.txt
  IF ERRORLEVEL 1 (
      ECHO Error deleting file
      EXIT /b 1
  )
  ECHO File deleted successfully
  ```

- **Missing error handling**: Flag operations that commonly fail without error checks
  ```batch
  # Bad
  COPY source.txt destination.txt
  
  # Good
  COPY source.txt destination.txt
  IF NOT ERRORLEVEL 1 ECHO Copy successful
  ```

### Potential Issues
- **Infinite loops**: Warn about potential infinite loops
  ```batch
  # Bad
  :loop
  ECHO Running
  GOTO loop
  
  # Good
  SET /a counter=0
  :loop
  SET /a counter+=1
  IF "%counter%" LSS 10 GOTO loop
  ```

- **Quoting**: Warn when variables containing spaces aren't properly quoted
  ```batch
  # Bad
  IF %PROGRAM_FILES%==C:\Program Files ECHO Match
  
  # Good
  IF "%PROGRAM_FILES%"=="C:\Program Files" ECHO Match
  ```

- **Network operations**: Warn about operations that may hang without timeouts
  ```batch
  # Bad
  PING google.com
  
  # Good
  PING -n 4 google.com
  ```

- **File locking**: Warn about operations on files that may be in use
  ```batch
  # Potentially problematic
  COPY "C:\Program Files\MyApp\config.ini" backup\
  
  # Better
  TASKLIST | FIND "myapp.exe" >nul
  IF NOT ERRORLEVEL 1 (
      ECHO Warning: MyApp may be using this file
  )
  COPY "C:\Program Files\MyApp\config.ini" backup\
  ```

- **PATH modifications**: Warn about permanent PATH changes vs temporary ones
  ```batch
  # Bad (permanent)
  SETX PATH "%PATH%;C:\MyApp"
  
  # Good (temporary)
  SET "PATH=%PATH%;C:\MyApp"
  ```

- **Errorlevel semantic differences**: Warn about the specific semantic difference between `IF %ERRORLEVEL% NEQ 1` and `IF NOT ERRORLEVEL 1`
  ```batch
  # Problematic - matches ANY value except 1 (0, 2, 3, 4...)
  IF %ERRORLEVEL% NEQ 1 (
      ECHO This matches success (0) AND other errors (2, 3, 4...)
  )
  
  # Correct - matches only success (errorlevel < 1, i.e., 0)
  IF NOT ERRORLEVEL 1 (
      ECHO This only matches success (errorlevel 0)
  )
  
  # Also correct - explicit success check
  IF %ERRORLEVEL% EQU 0 (
      ECHO This explicitly checks for success only
  )
  
  # Fine - other NEQ patterns don't have this issue
  IF %ERRORLEVEL% NEQ 0 (
      ECHO This correctly checks for any error
  )
  ```

### Enhanced Command Validation Warnings
- **FOR /F parsing options**: Warn when FOR /F lacks explicit tokens/delims options
  ```batch
  # Bad - No parsing options specified
  for /f %i in ('dir') do echo %i
  
  # Good - Explicit parsing options
  for /f "tokens=1,2 delims=," %i in (data.csv) do echo %i %j
  for /f "tokens=*" %i in ('dir') do echo %i
  ```

- **IF comparison quoting**: Warn when IF comparisons lack proper quoting
  ```batch
  # Bad - Variables may contain spaces
  if %username%==admin echo admin
  if %path%==C:\Program Files echo match
  
  # Good - Proper quoting handles spaces
  if "%username%"=="admin" echo admin
  if "%path%"=="C:\Program Files" echo match
  ```

- **Missing delayed expansion setup**: Warn when using !var! without proper SETLOCAL
  ```batch
  # Bad - Using !var! without enabling delayed expansion
  set var=hello
  echo !var!
  
  # Good - Proper delayed expansion setup
  setlocal EnableDelayedExpansion
  set var=hello
  echo !var!
  ```

- **Deprecated commands**: Warn about commands deprecated in modern Windows
  ```batch
  # Bad - Deprecated commands (W024)
  WMIC os get caption              :: Use PowerShell WMI cmdlets
  CACLS file.txt                   :: Use ICACLS
  WINRM quickconfig                :: Use PowerShell Remoting
  BITSADMIN /transfer test url dst :: Use PowerShell BitsTransfer
  NBTSTAT -n                       :: Use PowerShell Get-NetAdapter
  DPATH C:\DATA                    :: Modify PATH instead
  KEYS                             :: Use CHOICE or SET /P
  NET SEND computer "message"      :: Use MSG
  AT 14:00 script.bat              :: Use SCHTASKS
  
  # Good - Modern alternatives
  powershell -Command "Get-WmiObject Win32_OperatingSystem"
  ICACLS file.txt /grant user:F
  powershell -Command "Enter-PSSession -ComputerName server"
  powershell -Command "Start-BitsTransfer -Source url -Destination dst"
  powershell -Command "Get-NetAdapter"
  SET "PATH=%PATH%;C:\DATA"
  CHOICE /C YN /M "Continue"
  MSG computer "message"
  SCHTASKS /create /tn "Task" /tr script.bat /sc daily
  
  # Note: XCOPY is NOT deprecated
  # XCOPY is still supported, though ROBOCOPY is recommended for advanced scenarios
  XCOPY source dest /E /Y          :: Still valid
  ROBOCOPY source dest /E          :: Recommended for advanced features
  ```

- **Missing error redirection**: Warn when commands lack proper error handling
  ```batch
  # Bad - No error redirection
  del temp.txt
  copy file1.txt file2.txt
  
  # Good - Proper error redirection
  del temp.txt 2>nul
  copy file1.txt file2.txt 2>&1
  ```

### Line Ending Related Warnings
- **Multi-byte characters with line ending risks**: UTF-8 characters combined with non-CRLF line endings can cause parser errors
  ```batch
  # Bad - Multi-byte characters with Unix line endings
  @echo off\n
  echo ═══════════════\n
  
  # Good - ASCII characters OR ensure CRLF line endings
  @echo off\r\n
  echo ===============\r\n
  ```

- **GOTO/CALL risks**: Label parsing may fail with non-CRLF line endings
  ```batch
  # Potentially problematic with Unix line endings
  goto :main\n
  :main\n
  echo Hello\n
  
  # Safer - use CRLF line endings
  goto :main\r\n
  :main\r\n
  echo Hello\r\n
  ```

### Compatibility Issues
- **Windows version**: Flag commands not available in older Windows versions
  ```batch
  # May not work on older Windows
  CHOICE /c yn /m "Continue?"
  
  # More compatible
  SET /p answer="Continue? (y/n): "
  ```

- **Architecture**: Warn about 32-bit vs 64-bit specific operations
  ```batch
  # Architecture-specific
  REG QUERY "HKLM\SOFTWARE\Wow6432Node\MyApp"
  
  # Architecture-aware
  IF "%PROCESSOR_ARCHITECTURE%"=="AMD64" (
      REG QUERY "HKLM\SOFTWARE\Wow6432Node\MyApp"
  ) ELSE (
      REG QUERY "HKLM\SOFTWARE\MyApp"
  )
  ```

- **Unicode support**: Check for proper Unicode handling in file operations
  ```batch
  # May have issues with Unicode
  TYPE file.txt
  
  # Better Unicode support
  TYPE file.txt | MORE
  ```

- **Encoding**: Warn about non-ASCII characters that may cause issues
  ```batch
  # Bad
  ECHO Héllo Wörld
  
  # Good
  ECHO Hello World
  ```

## Style Level Rules
*Code style and formatting issues*

### Code Style
- **Echo statements**: Error on `ECHO OFF` without `@` prefix (should be `@ECHO OFF`)
  ```batch
  # Bad
  ECHO OFF
  
  # Good
  @ECHO OFF
  ```

- **File header**: Warn when `@ECHO OFF` is missing at the top of the file
  ```batch
  # Bad
  REM This script does something
  ECHO Hello World
  
  # Good
  @ECHO OFF
  REM This script does something
  ECHO Hello World
  ```

- **Command capitalization**: Recommend uppercase for all batch commands following standard conventions
  ```batch
  # Bad
  echo Hello
  set var=value
  if exist file.txt del file.txt
  
  # Good
  ECHO Hello
  SET var=value
  IF EXIST file.txt DEL file.txt
  ```

- **Case sensitivity**: Flag inconsistent casing in commands
  ```batch
  # Inconsistent (warn)
  ECHO Hello
  echo World
  
  # Consistent
  ECHO Hello
  ECHO World
  ```

- **Trailing whitespace**: Detect and warn about trailing spaces/tabs
  ```batch
  # Bad (spaces after command)
  ECHO Hello   
  
  # Good
  ECHO Hello
  ```

- **Line endings**: Warn about mixed line endings (CRLF vs LF)
  ```batch
  # Bad: Mixed line endings in same file
  ECHO Line 1\r\n
  ECHO Line 2\n
  
  # Good: Consistent CRLF line endings
  ECHO Line 1\r\n
  ECHO Line 2\r\n
  ```

- **Double-colon comments**: May be unsafe with non-CRLF line endings
  ```batch
  # Potentially problematic with Unix line endings
  @echo off\n
  :: This comment might be misinterpreted\n
  echo Hello\n
  
  # Safer approach
  @echo off\r\n
  REM This comment is always safe\r\n
  echo Hello\r\n
  ```

### Variable Naming
- **Variable naming**: Enforce consistent naming conventions
  ```batch
  # Inconsistent
  SET myvar=value
  SET ANOTHER_VAR=value2
  
  # Consistent
  SET MY_VAR=value
  SET ANOTHER_VAR=value2
  ```

### File Extensions
- The `.cmd` file extension is recommended over the `.bat` file extension
  ```batch
  # Recommended: script.cmd
  # Not recommended: script.bat
  ```

### Code Quality
- **Comments**: Encourage documentation for complex sections
  ```batch
  # Bad
  FOR /f "tokens=2 delims==" %%a IN ('WMIC os get localdatetime /value') DO SET dt=%%a
  
  # Good
  REM Get current date/time in format YYYYMMDDHHMMSS
  FOR /f "tokens=2 delims==" %%a IN ('WMIC os get localdatetime /value') DO SET dt=%%a
  ```

- **Magic numbers**: Flag hardcoded values that should be variables
  ```batch
  # Bad
  TIMEOUT /t 30
  
  # Good
  SET TIMEOUT_SECONDS=30
  TIMEOUT /t "%TIMEOUT_SECONDS%"
  ```

- **Dead code**: Detect unused labels or unreferenced subroutines
  ```batch
  # Bad
  GOTO main
  :unused_label
  ECHO This is never called
  :main
  ECHO Hello
  
  # Good
  ECHO Hello
  ```

### Advanced Style and Best Practice Rules
- **Variable naming consistency**: Enforce consistent variable naming conventions
  ```batch
  # Bad - Inconsistent case styles
  set UPPERCASE_VAR=value
  set lowercase_var=value
  set MiXeD_CaSe=value
  
  # Good - Consistent naming
  set GLOBAL_VAR=value
  set ANOTHER_GLOBAL=value
  ```

- **Function documentation**: Require documentation for functions and subroutines
  ```batch
  # Bad - No documentation
  :MyFunction
  echo Processing
  goto :eof
  
  # Good - Documented function
  REM Function: ProcessFile
  REM Purpose: Processes a file and creates backup
  REM Parameters: %1 = filename to process
  REM Returns: Sets RESULT variable to success/failure
  :ProcessFile
  echo Processing %1
  goto :eof
  ```

- **Magic numbers**: Flag numeric literals that should be named constants
  ```batch
  # Bad - Magic numbers
  timeout 3600
  ping -n 86400 localhost
  
  # Good - Named constants
  set HOUR_SECONDS=3600
  set DAY_SECONDS=86400
  timeout %HOUR_SECONDS%
  ping -n %DAY_SECONDS% localhost
  ```

- **Line length and continuation**: Flag long lines that should use continuation
  ```batch
  # Bad - Very long line
  copy "C:\Very\Long\Path\With\Many\Directories\file.txt" "C:\Another\Very\Long\Destination\Path\file.txt"
  
  # Good - Use continuation
  copy "C:\Very\Long\Path\With\Many\Directories\file.txt" ^
       "C:\Another\Very\Long\Destination\Path\file.txt"
  ```

## Security Level Rules
*Security-related issues that could pose risks*

### Input Validation
- **Command injection**: Detect potential injection vulnerabilities
  ```batch
  # Bad
  SET /p input="Enter filename: "
  DEL %input%
  
  # Good
  SET /p input="Enter filename: "
  IF DEFINED input DEL "%input%"
  ```

- **Unsafe SET usage**: Warn about SET commands without proper validation or quoting
  ```batch
  # Bad
  SET var=Hello World
  SET /p userfile="Enter file: "
  COPY %userfile% backup\
  
  # Good  
  SET "var=Hello World"
  SET /p userfile="Enter file: "
  IF DEFINED userfile COPY "%userfile%" backup\
  ```

### Dangerous Operations
- **Dangerous commands**: Warn about destructive commands without confirmation
  ```batch
  # Bad
  DEL *.* /q
  
  # Good
  SET /p confirm="Delete all files? (y/n): "
  IF /i "%confirm%"=="y" DEL *.* /q
  ```

- **Registry operations**: Flag potentially dangerous registry modifications
  ```batch
  # Dangerous
  REG DELETE "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion" /f
  
  # Safer
  REG QUERY "HKLM\SOFTWARE\MyApp" >nul 2>&1
  ```

### Privilege Issues
- **Elevated privileges**: Warn when scripts require admin rights but don't check
  ```batch
  # Bad
  REG ADD "HKLM\SOFTWARE\MyApp" /v Value /d Data
  
  # Good
  NET SESSION >nul 2>&1
  IF ERRORLEVEL 1 (
      ECHO This script requires administrator privileges
      EXIT /b 1
  )
  REG ADD "HKLM\SOFTWARE\MyApp" /v Value /d Data
  ```

### Path Security
- **Hardcoded paths**: Flag absolute paths that may not exist on other systems
  ```batch
  # Bad
  COPY "C:\Users\John\file.txt" dest
  
  # Good
  COPY "%USERPROFILE%\file.txt" dest
  ```

- **Temporary directory**: Suggest using `%TEMP%` instead of hardcoded temp paths
  ```batch
  # Bad
  ECHO data > C:\temp\myfile.txt
  
  # Good
  ECHO data > "%TEMP%\myfile.txt"
  ```

### Enhanced Security Rules
- **Path traversal attacks**: Detect potential directory traversal vulnerabilities
  ```batch
  # Bad - Path traversal risk
  copy file.txt ..\..\..\windows\system32\
  cd ..\..\..\sensitive\directory
  
  # Good - Validate paths, use absolute paths
  set "DEST_DIR=C:\Safe\Directory"
  copy file.txt "%DEST_DIR%\"
  ```

- **Unsafe temporary file creation**: Detect predictable temp file names
  ```batch
  # Bad - Predictable temp file
  echo content > c:\temp\myfile.tmp
  echo data > temp.txt
  
  # Good - Random component in temp files
  echo content > "%TEMP%\myfile_%RANDOM%.tmp"
  echo data > "temp_%RANDOM%_%TIME:~6,2%.txt"
  ```

- **Command injection via variables**: Detect variables used with shell operators
  ```batch
  # Bad - Variable content used with shell operators
  set user_input=hello & del *.*
  echo %user_input% | find "test"
  
  # Good - Validate and sanitize variables
  set "user_input=hello world"
  if defined user_input echo "%user_input%" | find "test"
  ```

## Performance Level Rules
*Performance-related suggestions and optimizations*

### Redundancy
- **Redundant operations**: Detect unnecessary file existence checks
  ```batch
  # Bad
  IF EXIST file.txt DEL file.txt
  IF EXIST file.txt ECHO File still exists
  
  # Good
  IF EXIST file.txt (
      DEL file.txt
      IF EXIST file.txt ECHO File still exists
  )
  ```

- **Code duplication**: Identify repeated code blocks that could be functions
  ```batch
  # Bad
  ECHO Processing file1
  COPY file1.txt backup\
  IF ERRORLEVEL 1 ECHO Error copying file1
  ECHO Processing file2
  COPY file2.txt backup\
  IF ERRORLEVEL 1 ECHO Error copying file2
  
  # Good
  CALL :backup_file file1.txt
  CALL :backup_file file2.txt
  GOTO :EOF
  
  :backup_file
  ECHO Processing %1
  COPY "%1" backup\
  IF ERRORLEVEL 1 ECHO Error copying %1
  GOTO :EOF
  ```

### Resource Management
- **Unnecessary setlocal**: `SETLOCAL` is not needed if there is no `SET` command
  ```batch
  # Bad
  SETLOCAL
  ECHO Hello World
  
  # Good
  ECHO Hello World
  ```

- **Unnecessary enabledelayedexpansion**: `SETLOCAL ENABLEDELAYEDEXPANSION` is not needed if there are no `!VARIABLES!`
  ```batch
  # Bad
  SETLOCAL ENABLEDELAYEDEXPANSION
  ECHO "%PATH%"
  
  # Good
  SETLOCAL
  ECHO "%PATH%"
  ```

- **Unnecessary endlocal**: `ENDLOCAL` is not needed if there is no `SETLOCAL`
  ```batch
  # Bad
  ECHO Hello World
  ENDLOCAL
  
  # Good
  ECHO Hello World
  ```

- **Missing endlocal before exit**: If there is a `SETLOCAL` in the script, there should be an `ENDLOCAL` before every exit
  ```batch
  # Bad
  SETLOCAL
  SET MY_VAR=value
  IF ERRORLEVEL 1 EXIT /b 1
  ECHO Success
  EXIT /b 0
  
  # Good
  SETLOCAL
  SET MY_VAR=value
  IF ERRORLEVEL 1 (
      ENDLOCAL
      EXIT /b 1
  )
  ECHO Success
  ENDLOCAL
  EXIT /b 0
  ```

### File Operations
- Temporary files should have %RANDOM% in their name to prevent file collisions
  ```batch
  # Bad
  ECHO data > temp.txt
  
  # Good
  ECHO data > "temp_%RANDOM%.txt"
  ```

### Enhanced Performance Rules
- **String operation efficiency**: Detect multiple operations that could be combined
  ```batch
  # Bad - Multiple separate string operations
  set var=%original:old1=new1%
  set var=%var:old2=new2%
  set var=%var:~0,10%
  
  # Good - Combined operations where possible
  set "temp=%original:old1=new1%"
  set "var=%temp:old2=new2:~0,10%"
  ```

- **DIR command optimization**: Suggest /B flag for performance when processing output
  ```batch
  # Bad - Verbose DIR output processed
  dir *.txt | findstr "test"
  for /f %i in ('dir *.log') do echo %i
  
  # Good - /B flag for bare format
  dir /b *.txt | findstr "test"
  for /f %i in ('dir /b *.log') do echo %i
  ```

- **Unnecessary command output**: Detect commands producing unwanted output
  ```batch
  # Bad - Output not redirected when unnecessary
  echo "Processing started..."
  type readme.txt
  dir
  
  # Good - Redirect output when appropriate
  echo "Processing started..." >nul
  type readme.txt >output.log
  dir >nul 2>&1
  ```

- **P026: Redundant DISABLEDELAYEDEXPANSION**: Detect unnecessary explicit disabling of delayed expansion
  ```batch
  # Bad - Redundant (delayed expansion is disabled by default)
  ECHO Starting script
  ECHO Processing
  ECHO More processing
  ECHO More processing
  ECHO More processing
  ECHO More processing
  ECHO More processing
  ECHO More processing
  ECHO More processing
  ECHO More processing
  ECHO More processing
  SETLOCAL DISABLEDELAYEDEXPANSION
  SET VAR=value
  ECHO %VAR%
  
  # Good - Removed redundant command
  ECHO Starting script
  ECHO Processing
  SET VAR=value
  ECHO %VAR%
  
  # OK - Defensive programming at script start (lines 1-10)
  @ECHO OFF
  SETLOCAL DISABLEDELAYEDEXPANSION
  SET VAR=value
  ECHO %VAR%
  
  # OK - Toggling pattern after ENDLOCAL
  SETLOCAL ENABLEDELAYEDEXPANSION
  SET VAR=test
  ECHO !VAR!
  ENDLOCAL
  
  SETLOCAL DISABLEDELAYEDEXPANSION
  SET VAR2=value
  ECHO %VAR2%
  
  # OK - Protecting literal ! characters
  SETLOCAL DISABLEDELAYEDEXPANSION
  ECHO Warning! This is important
  SET MSG=Alert! Check this
  
  # OK - Combined with ENABLEEXTENSIONS (common pattern)
  SETLOCAL ENABLEEXTENSIONS DISABLEDELAYEDEXPANSION
  SET PATH=%PATH%;C:\Tools
  ```

## Operational Limits and Configuration

Blinter enforces resource limits to keep analysis predictable on large directories and files:

| Setting | Default | Description |
|---------|---------|-------------|
| `MAX_FILE_SIZE_BYTES` | 50 MB | Maximum batch file size read from disk |
| `max_scan_files` (`blinter.ini`) | 1000 | Maximum `.bat`/`.cmd` files discovered in one directory scan |
| `MAX_FOLLOW_CALL_FILES` | 100 | Maximum scripts traversed when `--follow-calls` is enabled |
| `MAX_FOLLOW_CALL_DEPTH` | 20 | Maximum CALL depth when following dependencies |
| `max_line_length` (`blinter.ini`) | 100 | Line length threshold for rule S011 |

When a directory scan exceeds `max_scan_files`, discovery raises an error. Narrow the path, disable recursive scanning, or increase `max_scan_files` in `blinter.ini`.

### Inline Suppressions

Scripts may suppress findings on a line using documentation comments:

- `REM LINT:IGNORE` or `:: LINT:IGNORE` — suppress all rules on that line
- `REM LINT:IGNORE E001,W001` — suppress specific rule codes on that line
- `REM LINT:IGNORE-LINE` — alternate form for line-level suppression

The directive and its rule codes match case-insensitively in ASCII only. A look-alike letter such as `ı` (U+0131) or `ſ` (U+017F) does not form a directive or a rule code. A directive that names codes, none of which are ASCII rule codes, suppresses nothing.

### Baseline file

`--baseline <path>` reads a JSON list of accepted findings. Each object has `code`, `file`, and `text`.
`file` is a POSIX path relative to the baseline file's directory. `text` is the trimmed source line.
Matching is a multiset: two identical lines need two entries.
A finding the baseline does not hold is reported and exits 1 only when its severity is at or above `fail_on`.
An entry whose file was scanned and that no longer matches a finding is stale and always exits 1.
Entries for files that were not scanned are left unchanged.

`--update-baseline` rewrites the file from the current findings, keeps entries for files outside the scan, and exits 0 unless a file could not be processed. It requires `--baseline`.

### blinter.ini Keys (general section)

- `recursive` — search subdirectories (default: `true`)
- `show_summary` — print summary statistics (default: `false`)
- `max_line_length` — S011 threshold (default: `100`)
- `max_scan_files` — directory scan cap (default: `1000`)
- `follow_calls` — analyze CALL targets (default: `false`)
- `min_severity` — minimum severity to report (`ERROR`, `SECURITY`, `WARNING`, `PERFORMANCE`, `STYLE`)
- `fail_on` — lowest severity that exits 1 (`error`, `security`, `warning`, `performance`, `style`, or `none`; default `security`). `--fail-on` overrides this key
