from django.db import models

class FoodPreference(models.TextChoices):
    VEG = "VEG", "Vegetarian"
    JAIN = "JAIN", "Jain"
    VEGAN = "VEGAN", "Vegan"
    SATVIK = "SATVIK", "Satvik"
    EGG_VEG = "EGG_VEG", "Egg Vegetarian"
    PESCETARIAN = "PESCETARIAN", "Pescetarian"
    GLUTEN_FREE = "GLUTEN_FREE", "Gluten Free"
    LACTOSE_FREE = "LACTOSE_FREE", "Lactose Free"
    DIABETIC_FRIENDLY = "DIABETIC_FRIENDLY", "Diabetic Friendly"
    NUT_ALLERGY = "NUT_ALLERGY", "Nut Allergy"
    HALAL = "HALAL", "Halal"
    NON_VEG_CHICKEN = "NON_VEG_CHICKEN", "Non Veg (Chicken Only)"
    NON_VEG_ANY = "NON_VEG_ANY", "Non Veg (Any)"

class TransportMode(models.TextChoices):
    TAXI = "TAXI", "Taxi"
    FLIGHT = "FLIGHT", "Flight"
    TRAIN = "TRAIN", "Train"
    SELF_ARRANGED = "SELF_ARRANGED", "Self Arranged"

class MedicalSupportType(models.TextChoices):
    WHEEL_CHAIR = "WHEEL_CHAIR", "Wheelchair Access"
    MOBILITY_ASSISTANCE = "MOBILITY_ASSISTANCE", "Mobility Assistance"
    ATTENDER = "ATTENDER", "Personal Attender"
    BLIND_COMPANION = "BLIND_COMPANION", "Blind Companion / Guide"
    HEARING_IMPAIRED = "HEARING_IMPAIRED", "Hearing Impaired Support"
    SIGN_LANGUAGE_INTERPRETER = "SIGN_LANGUAGE_INTERPRETER", "Sign Language Interpreter"
    OXYGEN_SUPPORT = "OXYGEN_SUPPORT", "Oxygen Support"
    GUIDE_DOG = "GUIDE_DOG", "Guide Dog Accommodation"
    RESERVED_SEATING = "RESERVED_SEATING", "Reserved Seating (Medical)"
    OTHER_MEDICAL = "OTHER_MEDICAL", "Other Medical Requirement"

class TranslationLanguage(models.TextChoices):
    HINDI = "HINDI", "Hindi"
    ENGLISH = "ENGLISH", "English"
    KANNADA = "KANNADA", "Kannada"
    TAMIL = "TAMIL", "Tamil"
    TELUGU = "TELUGU", "Telugu"
    MALAYALAM = "MALAYALAM", "Malayalam"
    PUNJABI = "PUNJABI", "Punjabi"
    BENGALI = "BENGALI", "Bengali"
    MARATHI = "MARATHI", "Marathi"
    GUJARATI = "GUJARATI", "Gujarati"
    ODIA = "ODIA", "Odia"
    ASSAMESE = "ASSAMESE", "Assamese"
    URDU = "URDU", "Urdu"

class RegistrationStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    ACCEPTED = "ACCEPTED", "Accepted"
    HOLD = "HOLD", "HOLD"
    REJECTED = "REJECTED", "Rejected"

class ApprovalStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    ACCEPTED = "ACCEPTED", "Accepted"
    REJECTED = "REJECTED", "Rejected"

class AttendanceMode(models.TextChoices):
    PHYSICAL = "PHYSICAL", "Physical (On-site)"
    VIRTUAL = "VIRTUAL", "Virtual (Online)"
    HYBRID = "HYBRID", "Hybrid"
    RECORDED = "RECORDED", "Recorded Session Only"
