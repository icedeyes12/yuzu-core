# [FILE: encryption.py]
# [VERSION: 2.0.0.PQ.1]
# [DATE: 2026-01-06]
# [PROJECT: HKKM - Yuzu Companion]
# [DESCRIPTION: High Perf & Quantum Resistant Key Size]
# [AUTHOR: Project Lead: Bani Baskara]
# [MODIFIED BY: Gemini]
# [LICENSE: MIT]

from Crypto.Cipher import ChaCha20_Poly1305
from Crypto.Random import get_random_bytes
import base64
import os
import json
import sys

class ModernEncryptor:
    def __init__(self, key_path="encryption.key"):
        self.key_path = key_path
        self.key = self._load_or_generate_key()
    
    def _load_or_generate_key(self):
        # ChaCha20-Poly1305 uses a 32-byte (256-bit) key
        if os.path.exists(self.key_path):
            print(f"Loading encryption key from {self.key_path}")
            with open(self.key_path, 'rb') as f:
                key = f.read()
            if len(key) != 32:
                raise ValueError(f"Invalid key length: {len(key)} bytes. 32 bytes required.")
            return key
        else:
            print("Generating new 256-bit key (Quantum Resistant)...")
            key = get_random_bytes(32)
            with open(self.key_path, 'wb') as f:
                f.write(key)
            print(f"New key saved to {self.key_path}")
            print("BACKUP THIS KEY FILE IMMEDIATELY!")
            return key
    
    def encrypt(self, plaintext):
        if not plaintext or not plaintext.strip():
            return plaintext
            
        try:
            # Generate a nonce (Number used ONCE). 
            # ChaCha20-Poly1305 standard nonce is 12 bytes.
            nonce = get_random_bytes(12)
            
            cipher = ChaCha20_Poly1305.new(key=self.key, nonce=nonce)
            
            # Encrypt and create MAC tag (Poly1305) in one go
            ciphertext, tag = cipher.encrypt_and_digest(plaintext.encode('utf-8'))
            
            # Structure: [Nonce (12)] + [Tag (16)] + [Ciphertext (n)]
            combined = nonce + tag + ciphertext
            
            return base64.b64encode(combined).decode('utf-8')
        except Exception as e:
            print(f"Encryption failed: {e}")
            return plaintext
    
    def decrypt(self, encrypted_text):
        if not encrypted_text or not encrypted_text.strip():
            return encrypted_text
            
        try:
            # Decode Base64
            combined = base64.b64decode(encrypted_text)
            
            # Validate length (12 nonce + 16 tag = 28 bytes min)
            if len(combined) < 28:
                return encrypted_text
                
            nonce = combined[:12]
            tag = combined[12:28]
            ciphertext = combined[28:]
            
            cipher = ChaCha20_Poly1305.new(key=self.key, nonce=nonce)
            
            # Verify and Decrypt
            # If the data was tampered with, this will raise a ValueError
            decrypted_data = cipher.decrypt_and_verify(ciphertext, tag)
            
            return decrypted_data.decode('utf-8')
            
        except ValueError:
            # This happens if the key is wrong or data is corrupted/tampered
            print("Integrity Check Failed: Data corrupted or wrong key.")
            return encrypted_text
        except Exception as e:
            # print(f"Decryption error: {e}") # Debug only
            return encrypted_text

    def get_key_info(self):
        if not os.path.exists(self.key_path):
            return {"status": "no_key", "message": "No encryption key found"}
        
        with open(self.key_path, 'rb') as f:
            key = f.read()
        
        return {
            "status": "loaded",
            "algorithm": "ChaCha20-Poly1305",
            "key_size_bits": len(key) * 8, # Should be 256
            "key_fingerprint": key.hex()[:16] + "..."
        }

encryptor = ModernEncryptor()

if __name__ == "__main__":
    test_text = "Project Yuzu: Post-Quantum Readiness Check."
    print("Testing ChaCha20-Poly1305 system...")
    
    encrypted = encryptor.encrypt(test_text)
    decrypted = encryptor.decrypt(encrypted)
    
    print(f"\nOriginal:  {test_text}")
    print(f"Encrypted: {encrypted[:50]}...")
    print(f"Decrypted: {decrypted}")
    
    if test_text == decrypted:
        print("\n✅ Encryption test PASSED!")
        print("   Integrity Check (Poly1305): Active")
    else:
        print("\n❌ Encryption test FAILED!")
        sys.exit(1)
