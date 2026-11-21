% Shapes declared in terms (hasShape, SHACL).
%
% These axioms constrain the models built with the ontology, not the ontology
% itself, so they need model facts:
%   instance_of(Instance, Class)       Class is a term of the ontology
%   holds(Relation, Source, Target)    e.g. holds(allocates, F, G)
% and are silent until such facts are asserted.
%
% shape_count(Owner, Shape, Target, Exempt, Path, Class, Min, Max): every
% instance of Target, unless it is an instance of one of the Exempt classes,
% has between Min and Max (none: unbounded) distinct values along Path that
% are instances of Class. Example, from feature-3se: a leaf goal is
% allocated to exactly one feature.
%
% The shapes of a term describe its relations with other concepts, each one
% targeting the target concept of the relation and looking back at its source
% along the inverse path. Without a stated cardinality they use Min 0 and no
% Max, so they document the relation and never produce a violation: other
% concepts may relate to the same target (attributes also allocate goals).

:- multifile violation/1, warning/1.

:- dynamic instance_of/2, holds/3.

instance_of_class(I, Class) :-
    instance_of(I, C0),
    is_a(C0, Class).

path_value(direct(Rel), I, V) :- holds(Rel, I, V).
path_value(inverse(Rel), I, V) :- holds(Rel, V, I).

violation(shape_count(Owner, Shape, I, Count, Min-Max)) :-
    shape_count(Owner, Shape, Target, Exempt, Path, Class, Min, Max),
    instance_of_class(I, Target),
    \+ ( member(E, Exempt), instance_of_class(I, E) ),
    findall(V, ( path_value(Path, I, V), instance_of_class(V, Class) ), Vs0),
    sort(Vs0, Vs),
    length(Vs, Count),
    (   Count < Min
    ;   Max \== none, Count > Max
    ).
