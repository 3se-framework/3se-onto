% Relation inheritance along subClassOf (mirrors scripts/check_inheritance.py).

:- dynamic
    sub_class_of/2,
    produces/2, consumes/2, conveys/2, exposes/2, fires/2.

%  A subclass is expected to declare the typed relations of its parent.
inherited_relation(produces).
inherited_relation(consumes).
inherited_relation(conveys).
inherited_relation(exposes).
inherited_relation(fires).

%! missing_inheritance(?Relation, ?Child, ?Parent, ?Target) is nondet.
%  Parent declares Relation to Target, Child is a direct subclass of Parent
%  and does not.
missing_inheritance(Rel, Child, Parent, Target) :-
    inherited_relation(Rel),
    sub_class_of(Child, Parent),
    Declared =.. [Rel, Parent, Target],
    call(Declared),
    Missing =.. [Rel, Child, Target],
    \+ call(Missing).
