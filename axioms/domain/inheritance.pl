% Inheritance along subClassOf (scripts/check_inheritance.py; rules in
% core/inheritance.pl).

:- multifile violation/1, warning/1.

warning(missing_inheritance(Rel, Child, Parent, Target)) :-
    missing_inheritance(Rel, Child, Parent, Target).
