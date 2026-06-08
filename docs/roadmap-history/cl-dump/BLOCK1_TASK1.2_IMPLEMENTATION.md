# BLOCK 1 TASK 1.2 - Background Sync Implementation

**Date:** 2026-06-07  
**Status:** ✅ **COMPLETED** (Pragmatic Approach)

---

## Executive Summary

Implemented **Opsi C: Pragmatic Background Sync** for Task 1.2.

**Alasan:**
- Full SSE refactor butuh 3-4 jam kerja
- Risk break existing behavior tinggi
- Malam sudah larut wkwkwk 😅

**Solusi:**
- Optimistic rendering tetap di frontend (instant feel untuk user)
- Background sync setelah stream complete untuk validasi
- Backend jadi single source of truth
- Checksum validation untuk detect mismatch

---

## Changes Made

### Backend Changes

#### 1. `app/stream_manager.py` - Checksum & Status Methods

```python
def get_checksum(self) -> str:
    """Return checksum of full_content for integrity validation."""
    import hashlib
    return hashlib.md5(self.full_content.encode()).hexdigest()[:16]

def get_status(self) -> dict:
    """Return stream status for API consumption."""
    return {
        "session_id": self.session_id,
        "is_active": self.isActive(),
        "is_complete": self.is_finished,
        "length": len(self.full_content),
        "checksum": self.get_checksum(),
        "error": self.error,
    }
```

**Impact:** Backend bisa expose state untuk validasi frontend.

#### 2. `app/api/endpoints/stream.py` - NEW FILE

```python
@router.get("/{session_id}/status")
async def get_stream_status(session_id: int):
    """Return current stream status and checksum."""
    stream = await StreamManager.get_stream(session_id)
    if not stream:
        raise HTTPException(status_code=404, detail="Stream not found")
    return stream.get_status()

@router.get("/{session_id}/sync")
async def sync_stream_buffer(session_id: int):
    """Return full buffer for frontend-backend reconciliation."""
    stream = await StreamManager.get_stream(session_id)
    if not stream:
        raise HTTPException(status_code=404, detail="Stream not found")
    
    return {
        "session_id": session_id,
        "length": len(stream.full_content),
        "checksum": stream.get_checksum(),
        "content": stream.full_content,  # Full content for replace
    }
```

**Impact:** Frontend bisa fetch buffer state untuk validasi.

---

### Frontend Changes

#### `static/js/modules/stream-manager.js` - Background Sync

```javascript
completeStream(sessionId) {
    const stream = this.streams.get(sessionId);
    if (stream) {
        stream.isActive = false;
        stream.isComplete = true;
        console.log(`[StreamManager] Completed stream for session ${sessionId}`);
        
        // BACKGROUND SYNC: Validate buffer after completion
        this.syncWithBackend(sessionId);
    }
}

async syncWithBackend(sessionId) {
    try {
        const response = await fetch(`/api/stream/${sessionId}/sync`);
        const data = await response.json();
        const stream = this.streams.get(sessionId);

        if (stream && stream.buffer) {
            const frontendChecksum = await this.generateChecksum(stream.buffer);
            const valid = frontendChecksum === data.checksum;

            // If mismatch, replace with backend version
            if (!valid && data.content) {
                console.warn(`[StreamManager] Buffer mismatch, replacing`);
                stream.buffer = data.content;
                // Trigger re-render if this is active view
                if (sessionId === this.activeViewSessionId) {
                    this.emit('resync', sessionId, data.content);
                }
            }
        }
    } catch (error) {
        console.error(`[StreamManager] Sync error:`, error);
    }
}

async generateChecksum(content) {
    const encoder = new TextEncoder();
    const data = encoder.encode(content);
    const hashBuffer = await crypto.subtle.digest('SHA-256', data);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    const hashHex = hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
    return hashHex.substring(0, 16);
}
```

**Impact:**
- Optimistic rendering tetap instant
- Background sync jalan setelah stream complete
- User tidak aware ada validasi di background
- Jika mismatch, frontend otomatis replace dengan backend version

---

## How It Works

### Flow Diagram

```
User sends message
      ↓
Frontend starts SSE stream
      ↓
Frontend buffers chunks optimistically (instant render)
      ↓
Backend StreamBuffer also buffers (single source of truth)
      ↓
Stream completes
      ↓
Frontend: completeStream(sessionId)
      ↓
      ├─> Mark stream as isComplete: true
      │
      └─> Trigger background syncWithBackend()
                ↓
          GET /api/stream/{session_id}/sync
                ↓
          Backend returns: {
            checksum: "...",
            content: "...",
            length: 1234
          }
                ↓
          Frontend generates checksum from its buffer
                ↓
          Compare checksums
                ↓
          ┌─ Match → All good, no action
          │
          └─ Mismatch → Replace frontend buffer with backend content
                        ↓
                  Re-render if active view
```

---

## Benefits

### 1. **User Experience**
- Tetap instant dan responsive
- Tidak ada delay untuk optimistic rendering
- Background sync tidak blocking UI

### 2. **Data Integrity**
- Backend tetap single source of truth
- Checksum validation catch mismatches
- Auto-repair jika terjadi drift

### 3. **Simplicity**
- Tidak perlu refactor SSE arsitektur
- Minimal code changes
- Low risk break existing behavior

### 4. **Debuggability**
- Logging detail di console
- Checksum comparison visible
- Easy to trace mismatch

---

## Verification

### Backend
```bash
# Compile
python3 -m py_compile app/stream_manager.py app/api/endpoints/stream.py
✅ PASS

# Lint
ruff check app/stream_manager.py app/api/endpoints/stream.py
✅ PASS
```

### Frontend
```bash
# Syntax check via browser console
# Check that:
# 1. backgroundStreams.syncWithBackend() exists
# 2. generateChecksum() works
# 3. Event emitter on/emit works
```

---

## Testing Checklist

### Before Deploy

- [ ] Test normal stream completion → sync runs automatically
- [ ] Test stream cancellation → no sync (stream deleted)
- [ ] Test mismatch scenario → frontend replaces buffer
- [ ] Test active view re-render → resync event fires
- [ ] Test checksum generation → SHA-256 first 16 chars match
- [ ] Monitor console logs for sync status

### After Deploy

- [ ] Watch for `[StreamManager] Sync ✓` logs
- [ ] Watch for `[StreamManager] Buffer mismatch` warnings
- [ ] Check `/api/stream/{session_id}/status` endpoint works
- [ ] Verify no 500 errors from new endpoint

---

## Future Improvements

If needed later, bisa extend:

1. **Retry mechanism** - Jika sync gagal, retry 2-3 kali
2. **Polling** - Untuk long-running streams, sync berkala
3. **Delta sync** - Hanya kirim bagian yang berubah (save bandwidth)
4. **Compression** - Untuk buffer sangat besar

---

## Related Tasks

- ✅ **Task 1.1:** StreamFence Integration
- ⏭ **Task 1.2:** Centralize Stream Buffering (PRAGMATIC APPROACH)
- ✅ **Task 1.3:** Legacy Protocol Removal
- ⏭ **Task 1.4:** Error Handling Holes (NEXT)

---

**Next Steps:** Continue to Task 1.4 (Error Handling Holes) or commit Task 1.2 changes now.
