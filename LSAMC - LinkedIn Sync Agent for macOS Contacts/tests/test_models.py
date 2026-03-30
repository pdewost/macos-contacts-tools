import pytest
from src.models.profile import LinkedInProfile, Experience

def test_profile_to_note_summary():
    profile = LinkedInProfile(
        full_name="John Doe",
        linkedin_url="https://linkedin.com/in/johndoe",
        current_role="Senior Dev",
        company="Tech Corp",
        experience=[
            Experience(title="Dev", company="Tech Corp", start_date="2020", end_date="2024")
        ],
        skills=["Python", "AppleScript"]
    )
    
    summary = profile.to_note_summary()
    assert "#linkedin-sync" in summary
    assert "John Doe" not in summary # Note summary currently focuses on role/company
    assert "Senior Dev at Tech Corp" in summary
    assert "Python, AppleScript" in summary

def test_profile_parsing():
    data = {
        "full_name": "Jane Smith",
        "linkedin_url": "https://linkedin.com/in/janesmith",
        "current_role": "CTO",
        "company": "Growth Inc"
    }
    profile = LinkedInProfile(**data)
    assert profile.full_name == "Jane Smith"
    assert profile.company == "Growth Inc"

# Mocking Agent extraction would go here
# ...
