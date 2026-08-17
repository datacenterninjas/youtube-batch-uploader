# YouTube Auto Publisher --- V2 Implementation Plan

## 1. Objective

Upgrade the existing local YouTube auto-uploader into an AI-assisted
content publishing pipeline.

The system should evolve from:

> Video folder → YouTube upload

into:

> Video detected → stabilized → analyzed → metadata generated →
> thumbnail selected → approval → YouTube upload → archive → history

Instagram is intentionally out of scope for this version.

------------------------------------------------------------------------

## 2. Current System

The existing system already provides:

-   Folder monitoring
-   Public / Private / Unlisted folder mapping
-   File stabilization
-   Title sanitization
-   Upload quota management
-   Retry handling
-   Success/failure logging
-   Archive and failure folders
-   Single-instance locking
-   Tkinter monitoring dashboard

These components should be retained and incrementally improved rather
than rewritten unnecessarily.

------------------------------------------------------------------------

# Phase 1 --- SQLite Job & History System

## Goal

Replace the current combination of text logs, quota state, and folder
scanning with a persistent SQLite state database.

## Database

Create:

`youtube_publisher.db`

Suggested tables:

### videos

-   id
-   file_path
-   filename
-   file_hash
-   file_size
-   duration
-   resolution
-   frame_rate
-   privacy
-   status
-   title
-   description
-   tags
-   category
-   playlist
-   transcript
-   ai_confidence
-   youtube_video_id
-   youtube_url
-   upload_attempts
-   error_message
-   created_at
-   analyzed_at
-   approved_at
-   uploaded_at
-   archived_at

### upload_attempts

-   id
-   video_id
-   attempt_number
-   started_at
-   completed_at
-   status
-   error
-   retry_delay

### analysis

-   id
-   video_id
-   analysis_type
-   result
-   model
-   confidence
-   created_at

## Job States

Implement a predictable state machine:

`DISCOVERED`

→ `STABILIZING`

→ `READY_FOR_ANALYSIS`

→ `ANALYZING`

→ `METADATA_READY`

→ `AWAITING_APPROVAL`

→ `READY_TO_UPLOAD`

→ `UPLOADING`

→ `UPLOADED`

→ `ARCHIVED`

Possible failure states:

`ANALYSIS_FAILED`

`UPLOAD_FAILED`

`REJECTED`

## Duplicate Protection

Calculate a SHA-256 hash for each video.

Before processing:

1.  Calculate file hash.
2.  Check SQLite.
3.  If the hash already exists, mark the new file as duplicate.
4.  Do not upload it again.

This protects against accidental duplicate exports.

------------------------------------------------------------------------

# Phase 2 --- AI Video Analysis & Metadata Generation

## Goal

Automatically understand the video and generate YouTube metadata.

## Inputs

The AI analysis should use multiple signals:

1.  Filename
2.  Folder structure
3.  Video metadata
4.  Representative frames
5.  Optional transcript
6.  User-provided metadata, if available

Priority should be:

`User input > filename/folder context > video evidence > AI inference`

The AI must not invent uncertain information.

## Frame Extraction

Use FFmpeg to extract representative frames.

Initial implementation:

-   5--10 frames for short videos
-   10--15 frames for longer videos
-   Prefer scene changes when practical
-   Avoid extracting hundreds of frames unnecessarily

Store temporary analysis frames separately from the original video.

## AI Output

Generate structured JSON containing:

``` json
{
  "title": "",
  "description": "",
  "tags": [],
  "category": "",
  "summary": "",
  "detected_location": "",
  "detected_subjects": [],
  "content_type": "",
  "confidence": 0.0
}
```

## Metadata Rules

Title:

-   Maximum safe length
-   Remove invalid characters
-   Preserve meaningful proper nouns
-   Avoid clickbait unless configured
-   Avoid unsupported claims

Description:

-   Natural language
-   Useful context
-   No hallucinated facts
-   Optional channel-specific template

Tags:

-   Relevant terms only
-   Avoid excessive repetition
-   Include location/topic/subject where supported

Category:

-   Recommend a YouTube category
-   Validate against allowed categories

------------------------------------------------------------------------

# Phase 3 --- Transcript, Captions & Chapters

## Goal

Use audio as an additional source of video understanding and
automatically generate captions and chapters.

## Transcription

Extract audio using FFmpeg.

Run speech-to-text.

Store:

-   Full transcript
-   Language
-   Confidence
-   Timestamped segments

## Uses of Transcript

The transcript should feed:

-   Title generation
-   Description generation
-   Chapter generation
-   Subtitle generation
-   Content classification

## Chapters

Generate timestamped chapters based on:

-   Transcript topic changes
-   Scene changes
-   Major activity changes

Example:

``` text
00:00 Introduction
01:24 Entering George Town
03:41 Street Art
07:18 Local Food
10:42 Old Town Walk
14:15 Closing
```

## Captions

Generate a YouTube-compatible subtitle format such as:

`VTT`

Keep captions synchronized with transcript timestamps.

------------------------------------------------------------------------

# Phase 4 --- Automatic Thumbnail Selection

## Goal

Automatically identify the strongest frames for YouTube thumbnails.

## Candidate Generation

Extract 10--20 candidate frames.

## Scoring

Score candidates using:

-   Sharpness
-   Exposure
-   Subject visibility
-   Composition
-   Face visibility
-   Eye visibility
-   Motion blur
-   Visual uniqueness
-   Text obstruction
-   Overall visual quality

## Output

Select the top 3--5 candidates.

The dashboard should display them for approval.

Future enhancement:

Generate branded thumbnails with:

-   Channel branding
-   Text overlays
-   Consistent typography
-   Logo
-   AI-selected background/frame

------------------------------------------------------------------------

# Phase 5 --- Human Approval Dashboard

## Goal

Introduce a review stage before publishing.

## Dashboard Sections

### System Status

-   Uploader status
-   AI analyzer status
-   Current job
-   Last successful upload
-   Last failure

### Queue

Show:

-   Waiting
-   Analyzing
-   Awaiting approval
-   Ready
-   Uploading
-   Completed
-   Failed

### Approval Screen

Display:

-   Video filename
-   Video preview
-   Generated title
-   Description
-   Tags
-   Category
-   Suggested playlist
-   AI confidence
-   Thumbnail candidates
-   Transcript
-   Chapters

Actions:

`EDIT`

`APPROVE`

`REJECT`

## Approval Modes

Support three modes:

### AUTO

AI-generated metadata is automatically approved.

### REVIEW

Human approval is required.

### MANUAL

The system analyzes the video but does not publish automatically.

The default should be `REVIEW`.

------------------------------------------------------------------------

# 3. Recommended Project Structure

``` text
antigrav/
│
├── app.py
├── uploader.py
├── analyzer.py
├── metadata_generator.py
├── thumbnail_analyzer.py
├── transcription.py
├── database.py
├── queue_manager.py
├── dashboard.py
├── youtube_client.py
├── config.py
├── utils.py
│
├── config.json
├── client_secrets.json
├── token.pickle
├── youtube_publisher.db
│
├── videos_to_upload/
│   ├── Public/
│   ├── Private/
│   └── Unlisted/
│
├── processing/
│   ├── frames/
│   ├── audio/
│   └── thumbnails/
│
├── uploaded_archive/
│
└── failed_to_upload/
```

------------------------------------------------------------------------

# 4. Configuration

Move configurable values out of Python code.

Example:

``` json
{
  "daily_upload_limit": 6,
  "file_stability_seconds": 5,
  "max_upload_retries": 5,
  "approval_mode": "review",
  "ai_enabled": true,
  "transcription_enabled": true,
  "thumbnail_analysis_enabled": true,
  "generate_chapters": true,
  "default_category": "Travel & Events"
}
```

This allows behavior to be changed without modifying source code.

------------------------------------------------------------------------

# 5. Reliability Requirements

The system should survive:

-   Computer restart
-   Network failure
-   YouTube API errors
-   AI API failure
-   Interrupted upload
-   Interrupted analysis
-   File being copied while detected
-   Duplicate files
-   Invalid video files
-   Missing credentials
-   API quota exhaustion

A restart should resume from the last known SQLite state rather than
starting from scratch.

------------------------------------------------------------------------

# 6. Error Handling

Classify errors into:

### Retryable

-   Network timeout
-   Temporary server error
-   Connection reset
-   Temporary API failure

### Non-retryable

-   Invalid credentials
-   Invalid video
-   Permission denied
-   Invalid metadata
-   Unsupported format
-   Permanent API errors

Retryable failures use exponential backoff.

Non-retryable failures move the job into a failure state and display the
reason in the dashboard.

------------------------------------------------------------------------

# 7. Security

Never commit:

-   `client_secrets.json`
-   `token.pickle`
-   API keys
-   OAuth credentials
-   Database files containing sensitive information

Add a `.gitignore`.

Protect OAuth token files with appropriate filesystem permissions.

------------------------------------------------------------------------

# 8. Development Sequence

Implement in this order:

### Sprint 1

SQLite database and job state machine.

### Sprint 2

File hashing and duplicate detection.

### Sprint 3

FFmpeg metadata extraction and representative frame extraction.

### Sprint 4

AI metadata generation.

### Sprint 5

Transcription and timestamped captions.

### Sprint 6

Automatic chapter generation.

### Sprint 7

Thumbnail candidate extraction and scoring.

### Sprint 8

Dashboard approval workflow.

### Sprint 9

End-to-end integration testing.

### Sprint 10

Failure recovery and production hardening.

------------------------------------------------------------------------

# 9. Future Features --- Not Part of V2

After the five core capabilities are stable, consider:

-   Scheduled publishing
-   Automatic playlist assignment
-   YouTube Shorts generation
-   Automatic vertical video reframing
-   AI-generated thumbnail designs
-   Post-upload analytics
-   View/engagement monitoring
-   Automatic performance reports
-   Channel-specific AI writing style
-   Multiple YouTube channels
-   Cloud/offsite processing
-   Instagram Reels
-   Facebook publishing
-   TikTok publishing
-   Email/Telegram notifications

------------------------------------------------------------------------

# 10. V2 Web Application Workflow

The finished V2 application should behave like this:

``` text
Start app.py
        ↓
FastAPI web UI starts
        ↓
Background workers start
        ↓
Video dropped into folder
        ↓
File detected
        ↓
File stabilization check
        ↓
SHA-256 duplicate check
        ↓
SQLite job created
        ↓
Extract video metadata
        ↓
Extract representative frames
        ↓
Extract audio
        ↓
Generate transcript
        ↓
AI analyzes video
        ↓
Generate title
Generate description
Generate tags
Generate category
Generate chapters
        ↓
Select thumbnail candidates
        ↓
AI confidence check
        ↓
Dashboard shows approval page
        ↓
Human approval
        ↓
YouTube upload
        ↓
Upload captions
        ↓
Set thumbnail
        ↓
Archive original video
        ↓
Store YouTube video ID
        ↓
Dashboard updated in real time
```

The browser UI is the primary control surface for V2.

------------------------------------------------------------------------

# 11. V2 Technology Stack

Recommended stack:

  Component               Technology
  ----------------------- ------------------------------------
  Backend                 Python
  Web framework           FastAPI
  Templates               Jinja2
  Dynamic UI              HTMX
  Styling                 Lightweight CSS
  Client-side scripting   Vanilla JavaScript
  Database                SQLite
  Video processing        FFmpeg
  YouTube integration     YouTube Data API v3
  Background processing   Python worker threads/processes
  AI analysis             Configurable vision-capable LLM
  Transcription           Configurable speech-to-text engine

The architecture should remain modular so AI and transcription providers
can be changed without rewriting the uploader or web UI.

------------------------------------------------------------------------

# 12. Future Features --- Not Part of V2

The finished V2 pipeline should behave like this:

``` text
Video dropped into folder
        ↓
File detected
        ↓
File stabilization check
        ↓
SHA-256 duplicate check
        ↓
SQLite job created
        ↓
Extract video metadata
        ↓
Extract representative frames
        ↓
Extract audio
        ↓
Generate transcript
        ↓
AI analyzes video
        ↓
Generate title
Generate description
Generate tags
Generate category
Generate chapters
        ↓
Select thumbnail candidates
        ↓
AI confidence check
        ↓
Human approval
        ↓
YouTube upload
        ↓
Upload captions
        ↓
Set thumbnail
        ↓
Archive original video
        ↓
Store YouTube video ID
        ↓
Dashboard updated
```

The end goal is a reliable local publishing system where dropping a
video into the appropriate folder is enough to prepare almost the entire
YouTube publication package automatically, while retaining human control
over what actually gets published.
