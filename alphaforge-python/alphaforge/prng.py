"""
Mulberry32 PRNG — exact port of the JS implementation.

This is the most critical module. Every downstream computation depends on
this producing identical output to the JS mulberry32 for the same seed.

JS reference (from data.js):
    function mulberry32(seed) {
        return function() {
            seed |= 0; seed = seed + 0x6D2B79F5 | 0;
            let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
            t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
            return ((t ^ t >>> 14) >>> 0) / 4294967296;
        };
    }

All arithmetic is done in unsigned 32-bit space with explicit masking.
"""

from __future__ import annotations

import math

_MASK32 = 0xFFFFFFFF
_INCREMENT = 0x6D2B79F5


def _imul(a: int, b: int) -> int:
    """Emulate JavaScript Math.imul — low 32 bits of integer multiplication."""
    return ((a & _MASK32) * (b & _MASK32)) & _MASK32


class Mulberry32:
    """Stateful Mulberry32 PRNG matching the JS implementation exactly."""

    __slots__ = ("_seed",)

    def __init__(self, seed: int) -> None:
        self._seed = seed & _MASK32

    def __call__(self) -> float:
        # seed = seed + 0x6D2B79F5 | 0
        self._seed = (self._seed + _INCREMENT) & _MASK32

        # let t = Math.imul(seed ^ seed >>> 15, 1 | seed)
        t = _imul(self._seed ^ (self._seed >> 15), (1 | self._seed) & _MASK32)

        # t = (t + Math.imul(t ^ t >>> 7, 61 | t)) ^ t
        #   JS precedence: + binds tighter than ^, so (t + Math.imul(...)) ^ t
        #   JS ^ converts both operands to Int32 (same bit-pattern as & 0xFFFFFFFF)
        inner = _imul((t ^ (t >> 7)) & _MASK32, (61 | t) & _MASK32)
        t = ((t + inner) & _MASK32) ^ (t & _MASK32)
        t = t & _MASK32

        # return ((t ^ t >>> 14) >>> 0) / 4294967296
        result = (t ^ (t >> 14)) & _MASK32
        return result / 4294967296


def hash_string(s: str) -> int:
    """Port of JS hashString — djb2-variant hash returning a non-negative int.

    JS reference:
        function hashString(str) {
            let hash = 0;
            for (let i = 0; i < str.length; i++) {
                const char = str.charCodeAt(i);
                hash = ((hash << 5) - hash) + char;
                hash |= 0;
            }
            return Math.abs(hash);
        }
    """
    h = 0
    for ch in s:
        code = ord(ch)
        h = ((h << 5) - h + code) & _MASK32
        # Convert to signed int32 (JS |= 0 behavior)
        if h >= 0x80000000:
            h -= 0x100000000
    return abs(h)


def normal_random(rng: Mulberry32) -> float:
    """Box-Muller transform matching JS normalRandom call order.

    JS reference:
        function normalRandom(rng) {
            let u1, u2;
            do { u1 = rng(); } while (u1 === 0);
            u2 = rng();
            return Math.sqrt(-2.0 * Math.log(u1)) * Math.cos(2.0 * Math.PI * u2);
        }
    """
    u1 = rng()
    while u1 == 0.0:
        u1 = rng()
    u2 = rng()
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
