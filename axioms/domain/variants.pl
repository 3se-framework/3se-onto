% Variants.
% A variant is a variant of a base entity, not of another variant.

:- multifile violation/1, warning/1.

:- dynamic is_variant_of/2.

violation(variant_of_variant(V, B)) :-
    is_variant_of(V, B),
    is_variant_of(B, _).
