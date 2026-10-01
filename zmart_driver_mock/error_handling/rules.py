"""The kinds of error, and what to do about each one.

This table is meant to be the same for every ZMART driver. A new microscope
does not change it; it only writes a classifier that sorts its own errors
into these kinds. Changing a rule here changes how every command behaves,
which is exactly why it lives in one place.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Kind(Enum):
    """The kinds of problem a driver can meet."""

    REFUSED_BY_LIMITS = "refused by limits"
    BAD_REQUEST = "bad request"
    TEMPORARY = "temporary"
    PERMANENT = "permanent"
    UNKNOWN_READING = "unknown reading"
    UNCONFIRMED = "unconfirmed"
    CONNECTION_LOST = "connection lost"


class Action(Enum):
    """What a dispatcher does next."""

    RAISE = "raise"
    RETRY = "try again"
    RETURN_UNKNOWN = "return 'unknown'"
    NOT_CONFIRMED_YET = "count as not confirmed yet"
    SEND_AGAIN_THEN_GIVE_UP = "send again, then give up softly"
    NOT_APPLICABLE = "does not happen here"


@dataclass(frozen=True)
class Rule:
    """What the get and the set dispatcher do for one kind of problem.

    ``error`` is the exception the experiment finally sees when the rule
    ends in raising: ``ValueError`` when the request itself was wrong,
    ``RuntimeError`` when the microscope failed. ``None`` means the outcome
    is reported, not raised.
    """

    get: Action
    set: Action
    error: type[Exception] | None


RULES: dict[Kind, Rule] = {
    Kind.REFUSED_BY_LIMITS: Rule(Action.NOT_APPLICABLE, Action.RAISE, ValueError),
    Kind.BAD_REQUEST: Rule(Action.RAISE, Action.RAISE, ValueError),
    # A temporary problem is tried again. Only when every try has failed does
    # it reach the experiment, as a RuntimeError (set) or an unknown reading (get).
    Kind.TEMPORARY: Rule(Action.RETRY, Action.RETRY, RuntimeError),
    Kind.PERMANENT: Rule(Action.RAISE, Action.RAISE, RuntimeError),
    Kind.UNKNOWN_READING: Rule(Action.RETURN_UNKNOWN, Action.NOT_CONFIRMED_YET, None),
    Kind.UNCONFIRMED: Rule(Action.NOT_APPLICABLE, Action.SEND_AGAIN_THEN_GIVE_UP, None),
    Kind.CONNECTION_LOST: Rule(Action.RAISE, Action.RAISE, RuntimeError),
}
