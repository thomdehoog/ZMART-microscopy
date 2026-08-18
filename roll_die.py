"""Print a random whole number between one and six, like rolling a single die.

Run it from a terminal with:

    python roll_die.py

Each run prints one new number. If you would like several rolls at once, you can
ask for them by adding a count, for example ``python roll_die.py 5`` to see five
rolls in a row.

The numbers come from Python's ``random`` module. They are not truly random in
the physical sense, but they are unpredictable enough for everyday use such as
picking a well, shuffling the order of samples, or choosing which field of view
to image first. If you ever need randomness that is reproducible — so that a
colleague can repeat exactly the same sequence — see the note in ``roll_die``
below about seeding.
"""

import random
import sys

# A standard die has six faces, numbered one through six.
LOWEST_FACE = 1
HIGHEST_FACE = 6


def roll_die():
    """Return a single random whole number from 1 to 6, each equally likely.

    There is nothing to pass in, and you always get back one plain integer.
    Both ends of the range are included, so 1 and 6 can come up just as often
    as the numbers in between.

    If you want the same sequence of "random" numbers every time you run your
    analysis — which is helpful when you want a colleague to be able to
    reproduce it exactly — call ``random.seed(0)`` (or any other number you
    choose) once before calling this function.
    """
    return random.randint(LOWEST_FACE, HIGHEST_FACE)


def main():
    """Read how many rolls were asked for, then print that many numbers.

    If no number is given on the command line we print a single roll. If
    something that is not a positive whole number is given, we explain the
    problem and stop rather than guessing what was meant.
    """
    arguments = sys.argv[1:]

    if not arguments:
        number_of_rolls = 1
    else:
        try:
            number_of_rolls = int(arguments[0])
        except ValueError:
            print(f"Sorry, '{arguments[0]}' is not a whole number. "
                  f"Try something like: python roll_die.py 5")
            return 1
        if number_of_rolls < 1:
            print("Please ask for at least one roll, for example: python roll_die.py 3")
            return 1

    for _ in range(number_of_rolls):
        print(roll_die())

    return 0


if __name__ == "__main__":
    # ``sys.exit`` passes the result on to the terminal, so that other scripts
    # can tell whether this one finished happily (0) or ran into a problem (1).
    sys.exit(main())
