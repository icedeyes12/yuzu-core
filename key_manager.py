# [FILE: key_manager.py]
# [VERSION: 1.0.0.69.1]
# [DATE: 2025-08-12]
# [PROJECT: HKKM - Yuzu Companion]
# [DESCRIPTION: Encryption key management utility]
# [AUTHOR: Project Lead: Bani Baskara]
# [TEAM: Deepseek, GPT, Qwen, Aihara]
# [REPOSITORY: https://guthib.com/icedeyes12]
# [LICENSE: MIT]

#!/usr/bin/env python3
import argparse
import os
import sys
from encryption import encryptor
from backup import BackupManager

def main():
    parser = argparse.ArgumentParser(description="Yuzu Companion Encryption Key Manager")
    parser.add_argument('--backup', action='store_true', help='Backup encryption key')
    parser.add_argument('--restore', action='store_true', help='Restore encryption key from backup')
    parser.add_argument('--info', action='store_true', help='Show key information')
    parser.add_argument('--test', action='store_true', help='Test encryption/decryption')
    parser.add_argument('--backup-path', default='backup_encryption.key', help='Backup file path')
    parser.add_argument('--list-backups', action='store_true', help='List key backups')
    parser.add_argument('--backup-dir', default='backup', help='Backup directory path')
    
    args = parser.parse_args()
    
    backup_manager = BackupManager(args.backup_dir)
    
    if args.backup:
        print("Backing up encryption key...")
        key_files = backup_manager.backup_encryption_keys()
        if key_files:
            print("Key backup completed successfully")
        else:
            print("Key backup failed")
            sys.exit(1)
    
    elif args.restore:
        print("Restoring encryption key...")
        if backup_manager.restore_encryption_key():
            print("Key restore completed successfully")
        else:
            print("Key restore failed")
            sys.exit(1)
    
    elif args.info:
        info = encryptor.get_key_info()
        print("Encryption Key Information:")
        for key, value in info.items():
            print(f"  {key}: {value}")
    
    elif args.test:
        print("Testing encryption system...")
        test_messages = [
            "Hello, World!",
            "This is a secret message.",
            "User personal data should be encrypted.",
            "API keys are sensitive information."
        ]
        
        all_passed = True
        for test_msg in test_messages:
            encrypted = encryptor.encrypt(test_msg)
            decrypted = encryptor.decrypt(encrypted)
            
            if test_msg == decrypted:
                print(f"Test passed: '{test_msg}' -> encrypted -> decrypted")
            else:
                print(f"Test failed: '{test_msg}' -> encryption test failed!")
                all_passed = False
        
        if all_passed:
            print("All encryption tests passed!")
        else:
            print("Some tests failed!")
            sys.exit(1)
    
    elif args.list_backups:
        backup_manager.list_key_backups()
    
    else:
        parser.print_help()

if __name__ == "__main__":
    main()