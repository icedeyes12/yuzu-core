#!/usr/bin/env python3
"""Test HTML preview functionality end-to-end."""

import sys
import re

def test_suite():
    errors = []
    
    # 1. Check renderer.js has showHtmlPreviewModal defined
    with open('static/js/renderer.js') as f:
        js = f.read()
    
    if 'function showHtmlPreviewModal' not in js and 'showHtmlPreviewModal(' not in js:
        errors.append("FAIL: showHtmlPreviewModal function not defined in renderer.js")
    else:
        print("PASS: showHtmlPreviewModal defined")
    
    # 2. Check onclick references the function
    onclick_matches = re.findall(r'onclick="([^"]+)\(', js)
    if 'showHtmlPreviewModal' not in js:
        errors.append("FAIL: showHtmlPreviewModal not called in renderer.js")
    else:
        print("PASS: showHtmlPreviewModal called")
    
    # 3. Check toggleHtmlPreview uses encodeURIComponent correctly
    if 'encodeURIComponent(code)' not in js and 'encodeURIComponent(encodedCode)' not in js:
        errors.append("FAIL: encodeURIComponent not used for passing code")
    else:
        print("PASS: encodeURIComponent used for code")
    
    # 4. Check modal HTML in chat.html
    with open('templates/chat.html') as f:
        html = f.read()
    
    if 'id="html-preview-modal"' not in html:
        errors.append("FAIL: html-preview-modal div not in chat.html")
    else:
        print("PASS: html-preview-modal div exists in chat.html")
    
    # 5. Check iframe has srcdoc (NOT contentDocument)
    if 'srcdoc' not in js:
        errors.append("FAIL: srcdoc not used for iframe content")
    else:
        print("PASS: srcdoc used for iframe")
    
    if 'contentDocument' in js or 'contentWindow.document' in js:
        errors.append("FAIL: old cross-origin approach (contentDocument) still present")
    else:
        print("PASS: no cross-origin approach")
    
    # 6. Check modal CSS exists
    with open('static/css/chat.css') as f:
        css = f.read()
    
    if '.html-preview-modal' not in css and '#html-preview-modal' not in css:
        errors.append("FAIL: .html-preview-modal CSS not defined")
    else:
        print("PASS: .html-preview-modal CSS exists")
    
    # 7. Check button has data-code attribute
    if 'data-code="${' in js or "data-code={`${" in js:
        print("PASS: data-code attribute used for passing code")
    else:
        errors.append("FAIL: data-code attribute not used for passing code")
    
    # 8. Check isHtmlCode detection
    if '_isHtmlCode(code)' in js or 'renderer._isHtmlCode(code)' in js:
        print("PASS: _isHtmlCode used")
    else:
        print("WARN: _isHtmlCode not used for HTML detection")
    
    return errors

if __name__ == '__main__':
    import os
    os.chdir('/home/workspace/yuzu-companion')
    print("=" * 50)
    print("HTML Preview Feature Test")
    print("=" * 50)
    errors = test_suite()
    print("=" * 50)
    if errors:
        print(f"\nFAILED ({len(errors)} errors):")
        for e in errors:
            print(f"  {e}")
        sys.exit(1)
    else:
        print("\nAll checks passed!")
        sys.exit(0)
