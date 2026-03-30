#!/usr/bin/env python3
"""
Unit test for v4.8 B1-FIX: LinkedIn Handle Sanitization in LinkedInProfile.
Tests the validator (sanitize_linkedin_url) and the guard in get_handle().
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.models.profile import LinkedInProfile

def test(desc, passed):
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"  {status}: {desc}")
    return passed

all_pass = True

print("--- Test Suite: v4.8 LinkedIn Handle Validator ---\n")

# 1. Normal URL should pass through unchanged
p1 = LinkedInProfile(full_name="Test", linkedin_url="https://www.linkedin.com/in/john-doe-123")
all_pass &= test("Normal URL preserved", p1.linkedin_url == "https://www.linkedin.com/in/john-doe-123")
all_pass &= test("Normal handle extracted", p1.get_handle() == "john-doe-123")

# 2. Leading // should be stripped
p2 = LinkedInProfile(full_name="Test", linkedin_url="//www.linkedin.com/in/slug-test")
all_pass &= test("Leading // sanitized to https:", p2.linkedin_url == "https://www.linkedin.com/in/slug-test")
all_pass &= test("Handle from // URL is correct", p2.get_handle() == "slug-test")

# 3. Bare www. should be prefixed
p3 = LinkedInProfile(full_name="Test", linkedin_url="www.linkedin.com/in/another-slug")
all_pass &= test("Bare www. prefixed with https://", p3.linkedin_url == "https://www.linkedin.com/in/another-slug")
all_pass &= test("Handle from www. URL is correct", p3.get_handle() == "another-slug")

# 4. Space in handle should be rejected by get_handle()
p4 = LinkedInProfile(full_name="Test", linkedin_url="https://www.linkedin.com/in/Jean-Pierre Bokobza")
all_pass &= test("URL with space is kept as-is by validator", "Jean-Pierre Bokobza" in p4.linkedin_url)
all_pass &= test("get_handle() rejects space → returns ''", p4.get_handle() == "")

# 5. URL-encoded space (%20) should be rejected by get_handle()
p5 = LinkedInProfile(full_name="Test", linkedin_url="http://www.linkedin.com/in/%C3%89ric%20HEME")
all_pass &= test("get_handle() rejects %20 → returns ''", p5.get_handle() == "")

# 6. Empty URL should not crash
p6 = LinkedInProfile(full_name="Test", linkedin_url="")
all_pass &= test("Empty URL doesn't crash", p6.get_handle() == "")

# 7. A slug-only URL (no /in/) should still return the value if clean
p7 = LinkedInProfile(full_name="Test", linkedin_url="oliviersibony")
all_pass &= test("Slug-only URL returns slug if clean", p7.get_handle() == "oliviersibony")

print(f"\n--- {'ALL TESTS PASSED' if all_pass else 'SOME TESTS FAILED'} ---")
sys.exit(0 if all_pass else 1)
