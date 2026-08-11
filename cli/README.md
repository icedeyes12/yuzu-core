# Yuzu Companion — Inline CLI REPL

`yuzu` adalah terminal REPL ringan untuk Yuzu Companion. CLI berkomunikasi dengan backend FastAPI melalui HTTP dan SSE; tidak mengimpor database atau service internal.

## Menjalankan

```bash
# Terminal 1
yuzu-server

# Terminal 2
yuzu
# atau
python -m cli.app
```

Backend default adalah `http://localhost:5000`. Ubah dengan:

```bash
YUZU_BACKEND_URL=http://127.0.0.1:5000 yuzu
```

Riwayat input disimpan oleh `prompt_toolkit` di `~/.yuzu_history`. Lokasi dapat diubah melalui `YUZU_CLI_HISTORY`.

## Antarmuka

Pesan biasa dikirim dengan menekan Enter. Balasan ditampilkan dari atas ke bawah sebagai Markdown menggunakan `rich.live.Live`. Status pemanggilan tool ditampilkan redup agar tidak mengambil alih log percakapan.

Perintah tersedia:

| Perintah | Fungsi |
|---|---|
| `/help` | Tampilkan bantuan |
| `/sessions` | Tampilkan daftar session |
| `/switch <id>` | Pindah session |
| `/quit`, `/exit`, `/q` | Keluar |

Panah atas/bawah digunakan untuk mengakses history input terminal.

## Arsitektur

```text
cli/app.py       Inline async REPL, prompt_toolkit, dan rich rendering
cli/client.py    Async HTTP client dan parser structured SSE events
                 token, tool_call, tool_result, done

/api/send_message_stream   Streaming chat endpoint
/api/sessions/list          Daftar session
/api/sessions/switch        Pindah session
/api/chat_history            Muat history percakapan
```

CLI hanya menggunakan endpoint yang sudah tersedia. Tidak ada perubahan pada direktori `app/`.

## Dependensi

- `rich` untuk Markdown, panel, dan live rendering
- `prompt-toolkit` untuk input async dan history
- `httpx` untuk HTTP/SSE

CLI sengaja menggunakan REPL inline, bukan framework TUI full-screen, agar tetap ringan dan cocok untuk Termux/mobile.
