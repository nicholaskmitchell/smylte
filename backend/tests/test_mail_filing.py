"""Which of the owner's lists a suggested task goes in, and its title without
the class. Pure functions: no database, no network."""
from __future__ import annotations

import pytest

from smylted.mail.filing import route, tidy_title

LISTS = [("home", "Home"), ("work", "Work"), ("comp", "DC Composition"),
         ("commit", "Commitments"), ("trig", "DC Trigonometry"), ("for", "Forensics"),
         ("yb", "Yearbook"), ("pf", "Personal Finance"), ("psy", "DC Psychology"),
         ("ger", "German IV")]


@pytest.mark.parametrize("group, picked, memory, want", [
    ("DC Psychology", "", {}, ("psy", "name")),
    ("Dc Trigonometry", "", {}, ("trig", "name")),
    ("DC-Trigonometry", "", {}, ("trig", "name")),
    ("Personal Finance 614", "", {}, ("pf", "contains")),
    ("Personal Finance 614", "Personal Finance", {}, ("pf", "model")),
    ("Math", "DC Trigonometry", {}, ("trig", "model")),
    ("Math", "", {}, (None, "")),
    ("German Club", "", {}, (None, "")),
    ("Psychology Club", "", {}, (None, "")),
    ("Home and School Association", "", {}, (None, "")),
    ("Work Study Program", "", {}, (None, "")),
    ("Personal", "", {}, (None, "")),
    ("Ruby Bridges Youth Justice Award", "",
     {"ruby bridges youth justice award": "home"}, ("home", "remembered")),
    ("Ruby Bridges Youth Justice Award", "Commitments", {}, ("commit", "model")),
    ("DC Psychology", "", {"dc psychology": "home"}, ("psy", "name")),
    ("Math", "", {"math": "trig"}, ("trig", "remembered")),
    ("Math", "", {"math": "deleted"}, (None, "")),
    ("", "Yearbook", {}, ("yb", "model")),
    ("", "Nonexistent", {}, (None, "")),
    ("Yearbook Staff", "", {}, ("yb", "contains")),
    ("German IV 2", "", {}, ("ger", "contains")),
    ("German", "", {}, (None, "")),
    ("Personal Finance and Banking", "", {}, (None, "")),
])
def test_route(group, picked, memory, want):
    assert route(group, picked, LISTS, memory) == want


def test_route_with_two_lists_of_the_same_name_does_not_guess():
    dup = [("a", "DC Psychology"), ("b", "DC  psychology")]
    assert route("DC Psychology", "", dup, {}) == (None, "")


@pytest.mark.parametrize("title, names, want", [
    ('Complete assignment "4.2 - Anxiety Disorders" for DC Psychology', ['DC Psychology', 'DC Psychology'], '4.2 - Anxiety Disorders'),
    ('Complete Paying for College Study Guide for Personal Finance 614', ['Personal Finance 614', 'Personal Finance'], 'Paying for College Study Guide'),
    ('Submit Kansas City Berlin Wall Exhibition permission slip for German IV', ['German IV', 'German IV'], 'Kansas City Berlin Wall Exhibition permission slip'),
    ('Submit "What\'s After High School" assignment for Personal Finance', ['Personal Finance', 'Personal Finance'], "What's After High School"),
    ('Submit “What’s After High School” assignment for Personal Finance', ['Personal Finance'], 'What’s After High School'),
    ('Prepare for Chapter 1A Test in Dc Trigonometry', ['Dc Trigonometry', 'DC Trigonometry'], 'Chapter 1A Test'),
    ('Complete assignment “4.2 - Anxiety Disorders” in DC Psychology', ['DC Psychology'], '4.2 - Anxiety Disorders'),
    ('DC Psychology: 4.2 - Anxiety Disorders', ['DC Psychology'], '4.2 - Anxiety Disorders'),
    ('4.2 - Anxiety Disorders', ['DC Psychology'], '4.2 - Anxiety Disorders'),
    ('Homework 4.4 for DC Trigonometry', ['Math', 'DC Trigonometry'], 'Homework 4.4'),
    ('Homework 4.4 for MATH 240', ['MATH 240'], 'Homework 4.4'),
    ('Homework 4.4 for Math 240', ['Math'], 'Homework 4.4'),
    ('Homework for Math', ['Math'], 'Homework'),
    ('Math homework 4.4', ['Math', 'DC Trigonometry'], 'Math homework 4.4'),
    ('German Letter', ['German IV', 'German'], 'German Letter'),
    ('Careers in Personal Finance', ['Personal Finance'], 'Careers in Personal Finance'),
    ('Careers in Forensics', ['Forensics'], 'Careers in Forensics'),
    ('Women in Psychology', ['Psychology', 'DC Psychology'], 'Women in Psychology'),
    ('Chapter 3 Test in the Statistics class', ['Statistics'], 'Chapter 3 Test in the Statistics class'),
    ('Study for Chapter 3 Test in Statistics', ['Statistics'], 'Chapter 3 Test'),
    ('Yearbook', ['Yearbook'], 'Yearbook'),
    ('German IV', ['German IV'], 'German IV'),
    ('Notes in Home', [], 'Notes in Home'),
    ('Unit 1 Exam', ['C++ (Period 3)'], 'Unit 1 Exam'),
    ('C++ (Period 3): Unit 1 Exam', ['C++ (Period 3)'], 'Unit 1 Exam'),
    ('"Homework 4.4"', [], 'Homework 4.4'),
    ('Complete the "Lab 3" write-up', [], 'Lab 3 write-up'),
    ('Submit "Essay 2"', [], 'Essay 2'),
    ('Do it', [], 'Do it'),
    ('Complete the worksheet', ['Statistics'], 'Worksheet'),
    ('Finish iPhone app mockup for Yearbook', ['Yearbook'], 'iPhone app mockup'),
    ('Turn in lab notebook for Biology', ['Biology'], 'Lab notebook'),
    ('Do Unit 2 Notes', [], 'Unit 2 Notes'),
])
def test_tidy_title(title, names, want):
    assert tidy_title(title, names) == want

