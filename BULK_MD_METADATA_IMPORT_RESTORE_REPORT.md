# Bulk .md Metadata Import Restore

Applied on top of the uploaded `V3 - Copy.zip`.

## Goal
Restore the `.md` metadata upload path inside **Works → Bulk ingest…** without changing unrelated site logic, website UI, content, or build routing.

## What changed

### 1. Restored `.md` upload in Bulk image ingest
A new button is available in the bulk ingest dialog:

```text
Import .md metadata…
```

It accepts:

```text
*.md
*.markdown
```

### 2. Parser restored for the Stillmark metadata format
The parser supports the existing import style:

```text
# Metadata Import
## Project
...
## Work 01
File name:
Work ID:
Title:
Alt text:
Caption:
Tags:
Focal point:
Published:
Review status:
```

### 3. Project metadata is applied to the ingest form
When a `.md` file is imported, the dialog reads:

```text
Series
Series slug
Project type
Project title
Years
Location
Mood
Visibility
Review mode
Cover work ID
Opening
```

The series slug, year, location, review state, and published state are reflected in the preview form where appropriate.

### 4. Work metadata is used during ingest
Each work row reads:

```text
File name
Series
Series slug
Work ID
Title
Year
Location
Alt text
Caption
Tags
Focal point
Published
Review status
```

The ingest action now uses the provided title, alt text, caption, tags, focal point, year, location, published state, and review status instead of generating generic text.

### 5. Image filename matching is restored
The dialog first tries to find image files beside the `.md` file.

It also supports this workflow:

```text
Import .md metadata…
Choose images…
```

After images are chosen, the control panel matches them against the `.md` `File name:` rows, including numbered filenames such as:

```text
1. party-like-a-wound.png
```

### 6. Missing images are blocked safely
If a row exists in the `.md` but the image file is missing, the preview shows:

```text
image file not found
```

The ingest is blocked until the image is matched.

### 7. Series creation is handled safely
If the `.md` references a new series slug, the ingest creates the series before adding the works.

If the series already exists, the ingest does not overwrite the existing series payload; it only adds the new works.

## Files changed

```text
scripts/control_panel.py
```

No other source file was changed.

## Validation

Passed:

```text
python -m py_compile scripts/control_panel.py scripts/qt_backend.py build_site.py
node --check assets/js/portfolio.js
node --check assets/js/series.js
custom markdown parser regression against romeo_juliet_numbered_metadata_import.md
```

## Note about build validation

`python build_site.py` was not used as a success gate because the uploaded V3 package already contains a content validation issue unrelated to this patch:

```text
series[9].cover_work_id: None is not of type 'string'
```

That error existed in the package content and was not changed by this `.md` import restore.
