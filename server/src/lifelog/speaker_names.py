"""Generated alliterative human names for new speakers."""

import random

FIRST_NAMES: dict[str, list[str]] = {
    "a": ["Aaron", "Abigail", "Adam", "Alice", "Amber", "Andrew", "Anna", "Arthur"],
    "b": ["Barbara", "Benjamin", "Beth", "Brandon", "Brian", "Bruce", "Bryan", "Bella"],
    "c": [
        "Carl",
        "Caroline",
        "Catherine",
        "Charles",
        "Chloe",
        "Connor",
        "Craig",
        "Cynthia",
    ],
    "d": ["Daniel", "David", "Dawn", "Deborah", "Denise", "Diana", "Diane", "Dylan"],
    "e": ["Edward", "Elena", "Elias", "Elizabeth", "Emily", "Emma", "Eric", "Evan"],
    "f": ["Felix", "Fiona", "Floyd", "Frances", "Frank", "Frederick", "Faith", "Fern"],
    "g": ["Gabriel", "Gary", "George", "Grace", "Gregory", "Gwen", "Gavin", "Georgia"],
    "h": ["Hannah", "Harold", "Henry", "Holly", "Howard", "Helen", "Hugo", "Heather"],
    "i": ["Ian", "Ida", "Imogen", "Isaac", "Isabella", "Ivan", "Iris", "Ivy"],
    "j": ["Jack", "Jacob", "James", "Jane", "Jennifer", "Jessica", "John", "Julia"],
    "k": ["Karen", "Katherine", "Keith", "Kevin", "Kimberly", "Kyle", "Kate", "Kurt"],
    "l": ["Laura", "Lawrence", "Leonard", "Linda", "Lisa", "Louis", "Lucy", "Luke"],
    "m": ["Marcus", "Margaret", "Marie", "Martin", "Mary", "Megan", "Michael", "Mona"],
    "n": ["Nancy", "Natalie", "Nathan", "Neil", "Nicholas", "Nora", "Norman", "Nina"],
    "o": ["Oliver", "Olivia", "Oscar", "Owen", "Omar", "Otis", "Opal", "Odette"],
    "p": [
        "Patricia",
        "Patrick",
        "Paul",
        "Paula",
        "Peter",
        "Philip",
        "Pamela",
        "Peyton",
    ],
    "q": [
        "Quentin",
        "Quinn",
        "Quincy",
        "Queenie",
        "Quinton",
        "Quila",
        "Quana",
        "Quimby",
    ],
    "r": ["Rachel", "Raymond", "Rebecca", "Richard", "Robert", "Roger", "Rose", "Ryan"],
    "s": ["Samuel", "Sandra", "Sarah", "Scott", "Sean", "Sharon", "Susan", "Steve"],
    "t": ["Teresa", "Thomas", "Timothy", "Tina", "Todd", "Tyler", "Tamara", "Trevor"],
    "u": ["Ulysses", "Uma", "Ursula", "Umar", "Una", "Ugo", "Ursa", "Ulric"],
    "v": ["Valerie", "Vanessa", "Vera", "Victor", "Vincent", "Vivian", "Vance", "Vera"],
    "w": ["Walter", "Wanda", "Wayne", "Wendy", "William", "Willow", "Wyatt", "Wesley"],
    "y": ["Yolanda", "Yvonne", "Yuri", "Yusuf", "Yara", "Yemen", "Yancey", "Yadira"],
    "z": ["Zachary", "Zara", "Zelda", "Zoe", "Zane", "Zora", "Zeke", "Zina"],
}

LAST_NAMES: dict[str, list[str]] = {
    "a": [
        "Adams",
        "Allen",
        "Anderson",
        "Armstrong",
        "Ashley",
        "Austin",
        "Alvarez",
        "Abbott",
    ],
    "b": ["Bailey", "Baker", "Barnes", "Bell", "Bennett", "Brooks", "Brown", "Burke"],
    "c": ["Campbell", "Carter", "Chapman", "Clark", "Collins", "Cook", "Cooper", "Cox"],
    "d": ["Daniels", "Davis", "Dawson", "Diaz", "Dixon", "Douglas", "Duncan", "Dunn"],
    "e": [
        "Edwards",
        "Elliott",
        "Ellis",
        "Erickson",
        "Evans",
        "Easton",
        "Emerson",
        "Eaton",
    ],
    "f": [
        "Farmer",
        "Ferguson",
        "Fisher",
        "Fletcher",
        "Flores",
        "Ford",
        "Foster",
        "Freeman",
    ],
    "g": ["Garcia", "Gardner", "Gibson", "Gomez", "Gray", "Green", "Griffin", "Gupta"],
    "h": [
        "Hall",
        "Hamilton",
        "Harris",
        "Harrison",
        "Hayes",
        "Henderson",
        "Hill",
        "Howard",
    ],
    "i": [
        "Ibanez",
        "Ibarra",
        "Irving",
        "Iverson",
        "Ingalls",
        "Irwin",
        "Isaksen",
        "Ives",
    ],
    "j": [
        "Jackson",
        "James",
        "Jenkins",
        "Johnson",
        "Jones",
        "Jordan",
        "Jacobs",
        "Jensen",
    ],
    "k": ["Keller", "Kelly", "Kennedy", "Kim", "King", "Knight", "Kramer", "Kumar"],
    "l": ["Lambert", "Lane", "Lawson", "Lee", "Lewis", "Little", "Long", "Lopez"],
    "m": [
        "Marshall",
        "Martin",
        "Mason",
        "Matthews",
        "Miller",
        "Mitchell",
        "Moore",
        "Morgan",
    ],
    "n": ["Nash", "Nelson", "Newman", "Nguyen", "Nichols", "Norman", "Norris", "Nolan"],
    "o": ["Ortega", "Oliver", "Olson", "Ortiz", "Osborne", "Owen", "Oakes", "Ogden"],
    "p": [
        "Palmer",
        "Parker",
        "Patterson",
        "Payne",
        "Pearson",
        "Perry",
        "Porter",
        "Powell",
    ],
    "q": [
        "Quaid",
        "Quinn",
        "Quinton",
        "Quigley",
        "Quarles",
        "Quill",
        "Queen",
        "Quance",
    ],
    "r": [
        "Ramirez",
        "Reed",
        "Reyes",
        "Reynolds",
        "Richardson",
        "Rivera",
        "Roberts",
        "Russell",
    ],
    "s": ["Sanders", "Scott", "Shaw", "Silva", "Simmons", "Smith", "Sullivan", "Stone"],
    "t": [
        "Taylor",
        "Thomas",
        "Thompson",
        "Torres",
        "Turner",
        "Tucker",
        "Tyler",
        "Tate",
    ],
    "u": ["Upton", "Underwood", "Uribe", "Ulrich", "Udall", "Usher", "Urbina", "Utley"],
    "v": [
        "Vargas",
        "Vasquez",
        "Vaughn",
        "Vega",
        "Villarreal",
        "Vincent",
        "Vance",
        "Voss",
    ],
    "w": ["Walker", "Ward", "Watson", "Webb", "West", "White", "Williams", "Wilson"],
    "y": ["Yates", "Yeats", "Young", "York", "Ybarra", "Yoder", "Yowell"],
    "z": [
        "Zamora",
        "Zhang",
        "Zimmerman",
        "Zuniga",
        "Zane",
        "Zeller",
        "Zeigler",
        "Zorn",
    ],
}


def generate_speaker_name(existing: set[str]) -> str:
    """Generate an alliterative 'First Last' name not present in existing."""
    candidates: list[str] = []
    base_pair: tuple[str, str] | None = None
    for letter, firsts in FIRST_NAMES.items():
        for first in firsts:
            for last in LAST_NAMES.get(letter, []):
                full = f"{first} {last}"
                if base_pair is None:
                    base_pair = (first, last)
                if full not in existing:
                    candidates.append(full)
    if candidates:
        return random.choice(candidates)

    # All letter-appropriate names taken: append a numeric suffix.
    first, last = base_pair or ("Sam", "Stone")
    n = 2
    while f"{first} {last} {n}" in existing:
        n += 1
    return f"{first} {last} {n}"
