# CLI Tool Critical Fixes Report

**Date**: January 2025  
**Trigger**: GameMaker project loading failures during social tab implementation  
**Status**: ✅ **RESOLVED**

## Issues Discovered

### ❌ **Issue 1: Malformed Sprite JSON Generation**

**Problem**: CLI-generated sprite files contained invalid JSON that prevented GameMaker from loading the project.

**Error Messages**:
```
Error: Field "builtinName": expected.
C:\...\spr_tabBtn_social_friends.yy(68,34): Error: Field "builtinName": expected.
C:\...\spr_tabBtn_social_profile.yy(68,34): Error: Field "builtinName": expected.
```

**Root Cause**: 
- Sprite creation template in `assets.py` line 231 included incorrect `"%Name": "frames"` field
- This field should NOT exist in the tracks array according to GameMaker's JSON schema

**Impact**: Complete project loading failure

### ❌ **Issue 2: Incomplete Reference Updates During Asset Rename**

**Problem**: Asset rename operations left stale internal references, causing loading failures.

**Error Messages**:
```
Failed to load file 'C:\...\sprites\spr_tabBtn_social\spr_tabBtn_friends.yy'.
```

**Root Cause**:
- Reference scanner missed internal `.yy` filename references within sprite JSON files
- Only scanned for directory path changes, not filename changes within those directories

**Impact**: Broken asset references, project loading failure

### ❌ **Issue 3: Incorrect Layer Directory Structure** (DISCOVERED)

**Problem**: CLI-generated sprites created wrong layer directory structure, causing GameMaker to fail loading with "File missing for GMSprite" errors.

**Error Messages**:
```
File missing for GMSprite spr_tabBtn_social_friends: 
sprites\spr_tabBtn_social_friends\layers\884cb8470e2540609bfad170b5ba9028\ce98f980108641b3a381ae8fd0c57ceb.png
File missing for GMSprite spr_tabBtn_social_profile: 
sprites\spr_tabBtn_social_profile\layers\6710ee9ebc174948afb9f237a5b20f3f\b55528d0cbfa428a94d998b9adeee5e0.png
```

**Root Cause**:
- CLI created: `layers/[layer_uuid]/[frame_uuid].png` 
- GameMaker expects: `layers/[frame_uuid]/[layer_uuid].png`
- Bug in `assets.py` line 311 used wrong UUID for directory structure

**Impact**: Complete project loading failure for any project with CLI-generated sprites

## Fixes Implemented

### ✅ **Fix 1: Corrected Sprite JSON Template**

**File**: `tooling/gms_helpers/assets.py` line 231

**Change**:
```python
# BEFORE (incorrect):
{
    "$GMSpriteFramesTrack": "",
    "%Name": "frames",        # ← REMOVED: This field causes JSON parsing errors
    "builtinName": 0,
    ...
}

# AFTER (correct):
{
    "$GMSpriteFramesTrack": "",
    "builtinName": 0,         # ← Correct format matches GameMaker schema
    ...
}
```

### ✅ **Fix 2: Enhanced Reference Scanner**

**File**: `tooling/gms_helpers/reference_scanner.py` lines 185-195

**Addition**:
```python
# NEW: Catch internal .yy filename references within sprite directories
if '"path"' in line and f"/{old_name}.yy" in line:
    new_line = line.replace(f"/{old_name}.yy", f"/{new_name}.yy")
    self.references.append(AssetReference(
        file_path=sprite_yy,
        line_number=i + 1,
        old_text=line.strip(),
        new_text=new_line.strip(),
        reference_type="sprite_keyframe_filename",
        context=f"Sprite keyframe .yy filename reference"
    ))
```

### ✅ **Fix 3: Corrected Layer Directory Structure**

**File**: `tooling/gms_helpers/assets.py` lines 311-317

**Change**:
```python
# BEFORE (incorrect):
layer_dir = asset_folder / "layers" / layer_uuid  # Wrong: layer_uuid as parent
layer_image_path = layer_dir / f"{image_uuid}.png"

# AFTER (correct):
layer_dir = asset_folder / "layers" / image_uuid  # Correct: frame_uuid as parent  
layer_image_path = layer_dir / f"{layer_uuid}.png"
```

**Result**: CLI now creates proper `layers/[frame_uuid]/[layer_uuid].png` structure that GameMaker expects.

### ✅ **Fix 4: Enhanced Test Coverage**

**File**: `tests/python/test_workflow_enhanced.py`

**New Tests**:
1. `test_sprite_creation_json_format()` - Validates sprite JSON structure
2. `test_comprehensive_sprite_rename_catches_yy_filename_refs()` - Validates complete reference updates
3. `test_sprite_creation_layer_directory_structure()` - Validates correct layer directory structure

### ✅ **Fix 5: Updated Documentation**

**Files Updated**:
- `docs/CLI_HELPER_TOOLS.md` - Added troubleshooting section
- `.cursor/rules/gamemaker-rules.mdc` - Added CLI safety rules

## Immediate Fixes Applied

**Fixed Broken Project**:
1. Removed extra `"%Name": "frames"` fields from social sprite JSON files
2. Updated stale reference: `spr_tabBtn_friends.yy` → `spr_tabBtn_social.yy`
3. Validated project loads successfully in GameMaker

## Prevention Measures

### **Automated Safeguards**:
1. **Enhanced reference scanner** catches all types of asset references
2. **JSON validation tests** prevent malformed templates
3. **Comprehensive test coverage** validates asset operations

### **Process Improvements**:
1. **Always run maintenance validation** after CLI operations
2. **Test project loading** in GameMaker after asset changes  
3. **Use workflow commands** for complex operations like renaming
4. **Follow CLI safety rules** documented in cursor rules

### **Developer Guidelines**:
- ✅ Use `gms workflow rename` instead of manual rename operations
- ✅ Run `gms maintenance auto --verbose` after asset creation
- ✅ Test GameMaker project loading after CLI operations
- ✅ Validate JSON structure in automated tests

## Impact Assessment

**Before Fixes**:
- ❌ Project completely unable to load in GameMaker
- ❌ CLI tools generated invalid JSON
- ❌ Asset renaming left broken references
- ❌ Sprite layer directory structure was incorrect
- ❌ No comprehensive testing for these scenarios

**After Fixes**:
- ✅ Project loads successfully in GameMaker
- ✅ CLI tools generate valid JSON that matches GameMaker schema
- ✅ Asset renaming updates ALL references comprehensively
- ✅ Sprite layer directories use correct structure
- ✅ Comprehensive test coverage prevents regression

## Lessons Learned

1. **JSON Schema Validation Critical** - GameMaker has strict JSON requirements
2. **Reference Scanning Must Be Comprehensive** - Internal references are easily missed
3. **Directory Structure Matters** - GameMaker expects exact file/folder layouts
4. **Test Coverage Prevents Regressions** - Automated tests catch issues early
5. **Documentation Prevents Future Issues** - Clear guidelines prevent mistakes
6. **Always Test in GameMaker** - CLI validation alone is insufficient

---

**Result**: The CLI tools are now robust and reliable for GameMaker asset operations. The social tab implementation was completed successfully with these fixes in place. 