## Version 0.2.1
- Experimentally support file deletion in file headers
- Update index counting

## Version 0.2.0
- Move `GitPython` out of test requirements and into main requirements
- Fix a few outstanding bugs with how index lines were parsed
- Add support for regenerating missing index lines
  - Only support in the cases of file deletion, or rename, 
  as anything else would require parsing the patch changes to generate 
  the SHA, which is explicitly out of scope for now
  - Note that this is an experimental new feature that has not been tested

## Version 0.1.0
- Change project name from "code-diff-fixer" to "patch-fixer"
