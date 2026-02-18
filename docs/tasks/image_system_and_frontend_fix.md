Task: Image System Update + Frontend Bubble Fix (End-to-End)

Goal

Menyelesaikan dua hal sekaligus:

1. Menyatukan struktur message bubble image di frontend.


2. Menambahkan model image baru:

z-image-turbo

selectable dari UI

tersimpan di profile (persistent)




Semua perubahan harus:

Stabil

Konsisten dengan arsitektur tool-driven

Tidak merusak flow chat, memory, atau tools lain



---

Part 1 — Frontend Image Upload Bubble Fix

Problem

Struktur bubble berbeda antara:

realtime UI

history setelah reload


Case 1 — Image only

User sends:

[image]

Realtime UI:

[user bubble: "analyze this image"]
[user bubble: image]

After reload:

[user bubble: image]

Mismatch.


---

Case 2 — Text + Image

User sends:

"keren banget mobilnya"
[image]

Realtime UI:

[user bubble: text]
[user bubble: image]

After reload:

[user bubble: text + image]

Expected: seperti hasil reload.


---

Root Cause

static/js/chat.js
Function:

handleImageMessage()

Masih:

Inject fake text

Kirim text dan image sebagai message terpisah



---

Required Behavior

Image only

[user bubble: image]

Tidak ada:

fake text

“analyze this image”



---

Text + Image

Single bubble:

[user bubble:
    text
    image
]

Harus konsisten:

live UI

history reload



---

Required Code Change

File

static/js/chat.js

Function

handleImageMessage(text)

Replace with

handleImageMessage(text) {
    if (this.selectedImages.length === 0) return;

    // Build a single unified message containing text + images
    let combinedMarkdown = "";

    // If user typed text, include it
    if (text && text.trim()) {
        combinedMarkdown += text.trim() + "\n\n";
    }

    // Append all images as markdown
    this.selectedImages.forEach((image) => {
        const imageUrl = URL.createObjectURL(image);
        combinedMarkdown += `![Uploaded Image](${imageUrl})\n\n`;
    });

    // Send as a single user bubble
    addMessage("user", combinedMarkdown.trim());

    // Clear selected images after sending
    this.selectedImages = [];
}


---

Constraints (Frontend)

Do NOT:

Modify backend

Modify tool pipeline

Modify vision system

Inject auto text


Frontend only.


---

Acceptance Tests (Frontend)

Test 1 — Image only

Input:

[image]

Expected:

Live:

[user bubble: image]

Reload:

[user bubble: image]


---

Test 2 — Text + image

Input:

"keren banget mobilnya"
[image]

Expected:

[user bubble: text + image]

Same before and after reload.


---

Test 3 — Multiple images

Input:

[image1]
[image2]
[image3]

Expected:

Single bubble:

[user bubble:
    image1
    image2
    image3
]


---

Part 2 — Add z-image-turbo Model

Goal

Menambahkan model image baru:

z-image-turbo

ke sistem image generation.

User bisa:

Pilih model di config UI

Disimpan ke profile

Digunakan otomatis saat generate image



---

Scope

Modify:

tools/image_generate.py
database.py
web.py
templates/config.html
static/js/config.js

Do NOT modify:

tool registry logic
memory schema
chat loop
system personality


---

Step 1 — Database Change

Add column to profile

image_model TEXT DEFAULT 'hunyuan'

Migration logic

If column not exists:

Add it.

SQLite:

ALTER TABLE profile ADD COLUMN image_model TEXT DEFAULT 'hunyuan';


---

Step 2 — Load model from profile

In image generation logic:

profile = Database.get_profile(session_id)
image_model = profile.get("image_model", "hunyuan")

Pass this to tool:

generate_image(prompt, image_model)


---

Step 3 — Tool: image_generate.py

Support two models:

Model 1 — hunyuan (existing)

Endpoint:

https://chutes-hunyuan-image-3.chutes.ai/generate

Body:

{
  "prompt": prompt
}


---

Model 2 — z-image-turbo (new)

Endpoint:

https://chutes-z-image-turbo.chutes.ai/generate

Body:

{
  "prompt": prompt
}


---

Required logic

In tool:

if model == "z_turbo":
    url = Z_TURBO_ENDPOINT
elif model == "hunyuan":
    url = HUNYUAN_ENDPOINT
else:
    fallback to hunyuan

All other flow:

Same headers

Same response handling

Same image saving logic


No new pipeline.


---

Step 4 — Config UI

File

templates/config.html

Add section:

Image Generation Model

Dropdown:

Hunyuan (default)
Z Image Turbo

Values:

hunyuan
z_turbo


---

Step 5 — Frontend config logic

File:

static/js/config.js

When user selects model:

POST /api/update_profile
{
  "image_model": "z_turbo"
}


---

Step 6 — Backend endpoint

In:

web.py

Inside profile update handler:

profile["image_model"] = request.json["image_model"]
Database.update_profile(profile)


---

Acceptance Tests (Image Model)

Test 1 — Default

No config change.

User:

generate image of a sunset

Expected:

Uses:

hunyuan


---

Test 2 — Switch model

In config:

Select:

Z Image Turbo

Reload app.

Generate image again.

Expected:

Uses z-image-turbo endpoint

Setting persists after reload



---

Final Deliverable

System must have:

1. Fixed frontend image bubble structure


2. Persistent image model setting


3. z-image-turbo working via existing tool


4. No regression in:

chat

memory

weather

web search

vision context


---


After implementation:
- Review your own changes
- Run existing tests if available
- Perform basic runtime checks
- Ensure no syntax or integration errors
Commit only when the system is stable.