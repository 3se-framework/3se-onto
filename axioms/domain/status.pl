% Editorial status (schemas/term.schema.json).

:- multifile violation/1, warning/1.

valid_status(draft).
valid_status(under_review).
valid_status(reviewed).
valid_status(under_approval).
valid_status(approved).
valid_status(standard).

violation(invalid_status(T, S)) :-
    status(T, S),
    \+ valid_status(S).
