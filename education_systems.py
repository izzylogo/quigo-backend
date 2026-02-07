"""
Education system configurations for different countries.
Maps countries to their respective education levels.
"""

EDUCATION_SYSTEMS = {
    "Nigeria": {
        "levels": [
            "Primary 1", "Primary 2", "Primary 3", "Primary 4", "Primary 5", "Primary 6",
            "JSS 1", "JSS 2", "JSS 3",
            "SS 1", "SS 2", "SS 3"
        ]
    },
    "United States": {
        "levels": [
            "Kindergarten",
            "Grade 1", "Grade 2", "Grade 3", "Grade 4", "Grade 5",
            "Grade 6", "Grade 7", "Grade 8",
            "Grade 9", "Grade 10", "Grade 11", "Grade 12"
        ]
    },
    "United Kingdom": {
        "levels": [
            "Year 1", "Year 2", "Year 3", "Year 4", "Year 5", "Year 6",
            "Year 7", "Year 8", "Year 9",
            "Year 10", "Year 11",
            "Year 12", "Year 13"
        ]
    },
    "Canada": {
        "levels": [
            "Kindergarten",
            "Grade 1", "Grade 2", "Grade 3", "Grade 4", "Grade 5", "Grade 6",
            "Grade 7", "Grade 8", "Grade 9",
            "Grade 10", "Grade 11", "Grade 12"
        ]
    },
    "South Africa": {
        "levels": [
            "Grade R",
            "Grade 1", "Grade 2", "Grade 3", "Grade 4", "Grade 5", "Grade 6", "Grade 7",
            "Grade 8", "Grade 9",
            "Grade 10", "Grade 11", "Grade 12"
        ]
    },
    "Ghana": {
        "levels": [
            "Primary 1", "Primary 2", "Primary 3", "Primary 4", "Primary 5", "Primary 6",
            "JHS 1", "JHS 2", "JHS 3",
            "SHS 1", "SHS 2", "SHS 3"
        ]
    },
    "Kenya": {
        "levels": [
            "Grade 1", "Grade 2", "Grade 3", "Grade 4", "Grade 5", "Grade 6",
            "Grade 7", "Grade 8", "Grade 9",
            "Grade 10", "Grade 11", "Grade 12"
        ]
    },
    "India": {
        "levels": [
            "Class 1", "Class 2", "Class 3", "Class 4", "Class 5",
            "Class 6", "Class 7", "Class 8",
            "Class 9", "Class 10",
            "Class 11", "Class 12"
        ]
    }
}

def get_available_countries():
    """Return list of available countries."""
    return list(EDUCATION_SYSTEMS.keys())

def get_education_levels(country: str):
    """Get education levels for a specific country."""
    return EDUCATION_SYSTEMS.get(country, {}).get("levels", [])
