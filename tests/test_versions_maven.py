"""Versions Maven : ``ComparableVersion`` et les spécifications de ``VersionRange``.

Les tables ``CANONICAL`` (la forme canonique), ``ORDER`` (chaque cas comparé au suivant) et
``RANGES`` (chaque spécification lue ou refusée, et les versions de ``RANGE_VERSIONS`` qu'elle
contient) ont été relevées sur ``maven-artifact`` 3.9.16, lancé par Java 8, le 2026-11-01. Une
comparaison plus large (9 102 versions publiées de 67 artefacts de Maven Central et de Google
Maven, et les cas limites des tests de ``ComparableVersion`` : 4 980 600 comparaisons) n'a donné
aucun écart ; voir les notes de E25 dans ``PLAN.md``.

Deux écarts voulus : une version nue est une « recommandation », que ``VersionRange`` dit contenir
toutes les versions, et qu'ici n'accepte qu'elle (``RANGES`` donne ``=V`` pour elles) ;
``[1.0,2.0,3.0]`` (une borne haute « 2.0,3.0 ») est refusée.
"""

import pytest

from forceupdate import versions
from forceupdate.models import Ecosystem, Gap
from forceupdate.versions import InvalidConstraint, InvalidVersion
from forceupdate.versions.maven import MAVEN, MavenVersion

CANONICAL = [
    ('1', '1'), ('1.0', '1'), ('1.0.0', '1'), ('1-0', '1'), ('1.0-0', '1'), ('1-ga', '1'),
    ('1.ga', '1'), ('1-final', '1'), ('1.0.RELEASE', '1'), ('1.0.release', '1'), ('1RELEASE', '1'),
    ('1Final', '1'), ('1FINAL', '1'), ('1GA', '1'), ('1a', '1-a'), ('1-a', '1-a'),
    ('1.0-a', '1-a'), ('1.0.0-a', '1-a'), ('1.0a', '1-a'), ('1.0.0a', '1-a'), ('1x', '1-x'),
    ('1-x', '1-x'), ('1.0-x', '1-x'), ('1.0.0-x', '1-x'), ('1.0x', '1-x'), ('1.0.0x', '1-x'),
    ('1cr', '1-rc'), ('1rc', '1-rc'), ('1Cr', '1-rc'), ('1Rc', '1-rc'), ('1cR', '1-rc'),
    ('1rC', '1-rc'), ('1m3', '1-milestone-3'), ('1milestone3', '1-milestone-3'),
    ('1Milestone3', '1-milestone-3'), ('1MILESTONE3', '1-milestone-3'), ('1a1', '1-alpha-1'),
    ('1-alpha-1', '1-alpha-1'), ('1b2', '1-beta-2'), ('1-beta-2', '1-beta-2'),
    ('1-milestone-3', '1-milestone-3'), ('1X', '1-x'), ('1A', '1-a'), ('1B', '1-b'), ('1M', '1-m'),
    ('1-alpha2snapshot', '1-alpha-2-snapshot'), ('1-alpha2', '1-alpha-2'),
    ('1-alpha-123', '1-alpha-123'), ('1-beta123', '1-beta-123'), ('1-m2', '1-milestone-2'),
    ('1-m11', '1-milestone-11'), ('1-rc', '1-rc'), ('1-cr2', '1-rc-2'), ('1-rc123', '1-rc-123'),
    ('1-SNAPSHOT', '1-snapshot'), ('1-sp', '1-sp'), ('1-sp2', '1-sp-2'), ('1-sp123', '1-sp-123'),
    ('1-abc', '1-abc'), ('1-def', '1-def'), ('1-pom-1', '1-pom-1'),
    ('1-1-snapshot', '1-1-snapshot'), ('1-1', '1-1'), ('1-2', '1-2'), ('1-123', '1-123'),
    ('2.0', '2'), ('2.0.a', '2-a'), ('2-1', '2-1'), ('2.0.2', '2.0.2'), ('2.0.123', '2.0.123'),
    ('2.1.0', '2.1'), ('2.1-a', '2.1-a'), ('2.1b', '2.1-b'), ('2.1-c', '2.1-c'),
    ('2.1-1', '2.1-1'), ('2.1.0.1', '2.1.0.1'), ('2.2', '2.2'), ('2.123', '2.123'),
    ('11.a2', '11-alpha-2'), ('11.a11', '11-alpha-11'), ('11.b2', '11-beta-2'),
    ('11.b11', '11-beta-11'), ('11.m2', '11-milestone-2'), ('11.m11', '11-milestone-11'),
    ('11', '11'), ('11.a', '11-a'), ('11b', '11-b'), ('11c', '11-c'), ('11m', '11-m'),
    ('1.0.0.RC1', '1-rc-1'), ('1.0.0-RC1', '1-rc-1'), ('1.0.0-RC2', '1-rc-2'),
    ('1.0.0.RC2', '1-rc-2'), ('1.0.0.X1', '1-x-1'), ('1.0.0-X2', '1-x-2'), ('1.0.0.x1', '1-x-1'),
    ('1.0.0-x1', '1-x-1'), ('1.0.0.2147483648', '1.0.0.2147483648'),
    ('1.0.0.2147483647', '1.0.0.2147483647'), ('9999999999', '9999999999'),
    ('99999999999999999999', '99999999999999999999'), ('1.010', '1.10'), ('1.01', '1.1'),
    ('1.1', '1.1'), ('01.1', '1.1'), ('1.0+build', '1-+build'), ('1_0', '1-_'),
    ('1.0~rc1', '1-~rc-1'), ('1..0', '1'), ('1--0', '1'), ('1.-1', '1-1'), ('1-.1', '1-0.1'),
    ('-1', '1'), ('.1', '0.1'), ('1.', '1'), ('1-', '1'), ('1.0-alpha.1', '1-alpha.1'),
    ('1.0-alpha-1', '1-alpha-1'), ('1.0alpha1', '1-alpha-1'), ('1-sp-1', '1-sp-1'),
    ('1-ga-1', '1-1'), ('1-1.1', '1-1.1'), ('1-1-1', '1-1-1'), ('1-1-2', '1-1-2'),
    ('1.0-beta1-SNAPSHOT', '1-beta-1-snapshot'), ('1.0-SNAPSHOT', '1-snapshot'),
    ('1.0-20201231.123456-1', '1-20201231.123456-1'), ('2.0-alpha-1', '2-alpha-1'),
    ('2.0-beta-1', '2-beta-1'), ('2.0-rc-1', '2-rc-1'), ('2.0-M1', '2-milestone-1'),
    ('2.0.M1', '2-milestone-1'), ('2.0-m1', '2-milestone-1'), ('2.0-milestone-1', '2-milestone-1'),
    ('2.0-ea', '2-ea'), ('2.0-preview', '2-preview'), ('2.0-dev', '2-dev'), ('2.0-pre', '2-pre'),
    ('2.0-jre', '2-jre'), ('2.0-android', '2-android'), ('2.0.jre', '2-jre'), ('2.0-Final', '2'),
    ('2.0.Final', '2'), ('2.0.CR1', '2-rc-1'), ('2.0.Beta1', '2-beta-1'),
    ('2.0.Alpha1', '2-alpha-1'), ('9.4.51.v20230217', '9.4.51-v-20230217'), ('9.4.51', '9.4.51'),
    ('9.4.52.v20230823', '9.4.52-v-20230823'), ('4.0.0-alpha.11', '4-alpha.11'),
    ('4.0.0-alpha.2', '4-alpha.2'), ('5.0.0-alpha.11', '5-alpha.11'),
    ('42.2.25.jre6', '42.2.25-jre-6'), ('42.2.25.jre7', '42.2.25-jre-7'), ('42.2.25', '42.2.25'),
    ('9.4.1212.jre7', '9.4.1212-jre-7'), ('9.4.1212', '9.4.1212'), ('20040616', '20040616'),
    ('3.2.1', '3.2.1'), ('3.2.2', '3.2.2'), ('v1.0', 'v-1'), ('V1.0', 'v-1'), ('v2', 'v-2'),
    ('1.0-alpha', '1-alpha'), ('1.0-beta', '1-beta'), ('1.0-milestone', '1-milestone'),
    ('1.0-rc', '1-rc'), ('1.0-snapshot', '1-snapshot'), ('1.0-sp', '1-sp'), ('1.0-zzz', '1-zzz'),
    ('1.0-aaa', '1-aaa'), ('1.0-1', '1-1'), ('1.0.1', '1.0.1'), ('1.0-alpha1', '1-alpha-1'),
    ('1.0-alpha10', '1-alpha-10'), ('1.0-alpha2', '1-alpha-2'), ('1.0-RC1', '1-rc-1'),
    ('1.0-RC10', '1-rc-10'), ('1.0-RC2', '1-rc-2'), ('1.0.0-alpha.beta', '1-alpha-beta'),
    ('1.0-b', '1-b'), ('1.0-c', '1-c'), ('1.0-m', '1-m'), ('1.0-a1', '1-alpha-1'),
    ('1.0-b1', '1-beta-1'), ('1.0-c1', '1-c-1'), ('1.0-m1', '1-milestone-1'), ('1.0-x1', '1-x-1'),
    ('1.0.a1', '1-alpha-1'), ('1.0.b1', '1-beta-1'), ('1.0.m1', '1-milestone-1'),
    ('1-0.alpha', '1-alpha'), ('1-0-alpha', '1-alpha'), ('1.0.0-0', '1'), ('1.0.0-0.0', '1'),
    ('1.0-0.1', '1-0.1'), ('0', ''), ('0.0', ''), ('0.0.0', ''), ('00', ''), ('0.1', '0.1'),
    ('0.0.1', '0.0.1'), ('0-alpha', 'alpha'), ('0.0-rc1', 'rc-1'),
    ('1.2.3.4.5.6.7.8.9', '1.2.3.4.5.6.7.8.9'), ('3.0.0-M1', '3-milestone-1'),
    ('3.0.0-M10', '3-milestone-10'), ('3.0.0-M2', '3-milestone-2'), ('2.22.2', '2.22.2'),
    ('3.5.2', '3.5.2'), ('3.13.0', '3.13'), ('3.11.0', '3.11'), ('1.0-alpha-10', '1-alpha-10'),
    ('1.0-alpha-9', '1-alpha-9'),
]  # fmt: skip

ORDER = [
    ('1', '=', '1.0'), ('1.0', '=', '1.0.0'), ('1.0.0', '=', '1-0'), ('1-0', '=', '1.0-0'),
    ('1.0-0', '=', '1-ga'), ('1-ga', '=', '1.ga'), ('1.ga', '=', '1-final'),
    ('1-final', '=', '1.0.RELEASE'), ('1.0.RELEASE', '=', '1.0.release'),
    ('1.0.release', '=', '1RELEASE'), ('1RELEASE', '=', '1Final'), ('1Final', '=', '1FINAL'),
    ('1FINAL', '=', '1GA'), ('1GA', '<', '1a'), ('1a', '=', '1-a'), ('1-a', '=', '1.0-a'),
    ('1.0-a', '=', '1.0.0-a'), ('1.0.0-a', '=', '1.0a'), ('1.0a', '=', '1.0.0a'),
    ('1.0.0a', '<', '1x'), ('1x', '=', '1-x'), ('1-x', '=', '1.0-x'), ('1.0-x', '=', '1.0.0-x'),
    ('1.0.0-x', '=', '1.0x'), ('1.0x', '=', '1.0.0x'), ('1.0.0x', '>', '1cr'), ('1cr', '=', '1rc'),
    ('1rc', '=', '1Cr'), ('1Cr', '=', '1Rc'), ('1Rc', '=', '1cR'), ('1cR', '=', '1rC'),
    ('1rC', '>', '1m3'), ('1m3', '=', '1milestone3'), ('1milestone3', '=', '1Milestone3'),
    ('1Milestone3', '=', '1MILESTONE3'), ('1MILESTONE3', '>', '1a1'), ('1a1', '=', '1-alpha-1'),
    ('1-alpha-1', '<', '1b2'), ('1b2', '=', '1-beta-2'), ('1-beta-2', '<', '1-milestone-3'),
    ('1-milestone-3', '<', '1X'), ('1X', '>', '1A'), ('1A', '<', '1B'), ('1B', '<', '1M'),
    ('1M', '>', '1-alpha2snapshot'), ('1-alpha2snapshot', '<', '1-alpha2'),
    ('1-alpha2', '<', '1-alpha-123'), ('1-alpha-123', '<', '1-beta123'),
    ('1-beta123', '<', '1-m2'), ('1-m2', '<', '1-m11'), ('1-m11', '<', '1-rc'),
    ('1-rc', '<', '1-cr2'), ('1-cr2', '<', '1-rc123'), ('1-rc123', '<', '1-SNAPSHOT'),
    ('1-SNAPSHOT', '<', '1-sp'), ('1-sp', '<', '1-sp2'), ('1-sp2', '<', '1-sp123'),
    ('1-sp123', '<', '1-abc'), ('1-abc', '<', '1-def'), ('1-def', '<', '1-pom-1'),
    ('1-pom-1', '<', '1-1-snapshot'), ('1-1-snapshot', '<', '1-1'), ('1-1', '<', '1-2'),
    ('1-2', '<', '1-123'), ('1-123', '<', '2.0'), ('2.0', '<', '2.0.a'), ('2.0.a', '<', '2-1'),
    ('2-1', '<', '2.0.2'), ('2.0.2', '<', '2.0.123'), ('2.0.123', '<', '2.1.0'),
    ('2.1.0', '<', '2.1-a'), ('2.1-a', '<', '2.1b'), ('2.1b', '<', '2.1-c'),
    ('2.1-c', '<', '2.1-1'), ('2.1-1', '<', '2.1.0.1'), ('2.1.0.1', '<', '2.2'),
    ('2.2', '<', '2.123'), ('2.123', '<', '11.a2'), ('11.a2', '<', '11.a11'),
    ('11.a11', '<', '11.b2'), ('11.b2', '<', '11.b11'), ('11.b11', '<', '11.m2'),
    ('11.m2', '<', '11.m11'), ('11.m11', '<', '11'), ('11', '<', '11.a'), ('11.a', '<', '11b'),
    ('11b', '<', '11c'), ('11c', '<', '11m'), ('11m', '>', '1.0.0.RC1'),
    ('1.0.0.RC1', '=', '1.0.0-RC1'), ('1.0.0-RC1', '<', '1.0.0-RC2'),
    ('1.0.0-RC2', '=', '1.0.0.RC2'), ('1.0.0.RC2', '<', '1.0.0.X1'), ('1.0.0.X1', '<', '1.0.0-X2'),
    ('1.0.0-X2', '>', '1.0.0.x1'), ('1.0.0.x1', '=', '1.0.0-x1'),
    ('1.0.0-x1', '<', '1.0.0.2147483648'), ('1.0.0.2147483648', '>', '1.0.0.2147483647'),
    ('1.0.0.2147483647', '<', '9999999999'), ('9999999999', '<', '99999999999999999999'),
    ('99999999999999999999', '>', '1.010'), ('1.010', '>', '1.01'), ('1.01', '=', '1.1'),
    ('1.1', '=', '01.1'), ('01.1', '>', '1.0+build'), ('1.0+build', '<', '1_0'),
    ('1_0', '<', '1.0~rc1'), ('1.0~rc1', '>', '1..0'), ('1..0', '=', '1--0'),
    ('1--0', '<', '1.-1'), ('1.-1', '>', '1-.1'), ('1-.1', '>', '-1'), ('-1', '<', '.1'),
    ('.1', '<', '1.'), ('1.', '=', '1-'), ('1-', '>', '1.0-alpha.1'),
    ('1.0-alpha.1', '>', '1.0-alpha-1'), ('1.0-alpha-1', '=', '1.0alpha1'),
    ('1.0alpha1', '<', '1-sp-1'), ('1-sp-1', '<', '1-ga-1'), ('1-ga-1', '<', '1-1.1'),
    ('1-1.1', '>', '1-1-1'), ('1-1-1', '<', '1-1-2'), ('1-1-2', '>', '1.0-beta1-SNAPSHOT'),
    ('1.0-beta1-SNAPSHOT', '<', '1.0-SNAPSHOT'), ('1.0-SNAPSHOT', '<', '1.0-20201231.123456-1'),
    ('1.0-20201231.123456-1', '<', '2.0-alpha-1'), ('2.0-alpha-1', '<', '2.0-beta-1'),
    ('2.0-beta-1', '<', '2.0-rc-1'), ('2.0-rc-1', '>', '2.0-M1'), ('2.0-M1', '=', '2.0.M1'),
    ('2.0.M1', '=', '2.0-m1'), ('2.0-m1', '=', '2.0-milestone-1'),
    ('2.0-milestone-1', '<', '2.0-ea'), ('2.0-ea', '<', '2.0-preview'),
    ('2.0-preview', '>', '2.0-dev'), ('2.0-dev', '<', '2.0-pre'), ('2.0-pre', '>', '2.0-jre'),
    ('2.0-jre', '>', '2.0-android'), ('2.0-android', '<', '2.0.jre'),
    ('2.0.jre', '>', '2.0-Final'), ('2.0-Final', '=', '2.0.Final'), ('2.0.Final', '>', '2.0.CR1'),
    ('2.0.CR1', '>', '2.0.Beta1'), ('2.0.Beta1', '>', '2.0.Alpha1'),
    ('2.0.Alpha1', '<', '9.4.51.v20230217'), ('9.4.51.v20230217', '>', '9.4.51'),
    ('9.4.51', '<', '9.4.52.v20230823'), ('9.4.52.v20230823', '>', '4.0.0-alpha.11'),
    ('4.0.0-alpha.11', '>', '4.0.0-alpha.2'), ('4.0.0-alpha.2', '<', '5.0.0-alpha.11'),
    ('5.0.0-alpha.11', '<', '42.2.25.jre6'), ('42.2.25.jre6', '<', '42.2.25.jre7'),
    ('42.2.25.jre7', '>', '42.2.25'), ('42.2.25', '>', '9.4.1212.jre7'),
    ('9.4.1212.jre7', '>', '9.4.1212'), ('9.4.1212', '<', '20040616'), ('20040616', '>', '3.2.1'),
    ('3.2.1', '<', '3.2.2'), ('3.2.2', '>', 'v1.0'), ('v1.0', '=', 'V1.0'), ('V1.0', '<', 'v2'),
    ('v2', '<', '1.0-alpha'), ('1.0-alpha', '<', '1.0-beta'), ('1.0-beta', '<', '1.0-milestone'),
    ('1.0-milestone', '<', '1.0-rc'), ('1.0-rc', '<', '1.0-snapshot'),
    ('1.0-snapshot', '<', '1.0-sp'), ('1.0-sp', '<', '1.0-zzz'), ('1.0-zzz', '>', '1.0-aaa'),
    ('1.0-aaa', '<', '1.0-1'), ('1.0-1', '<', '1.0.1'), ('1.0.1', '>', '1.0-alpha1'),
    ('1.0-alpha1', '<', '1.0-alpha10'), ('1.0-alpha10', '>', '1.0-alpha2'),
    ('1.0-alpha2', '<', '1.0-RC1'), ('1.0-RC1', '<', '1.0-RC10'), ('1.0-RC10', '>', '1.0-RC2'),
    ('1.0-RC2', '>', '1.0.0-alpha.beta'), ('1.0.0-alpha.beta', '<', '1.0-b'),
    ('1.0-b', '<', '1.0-c'), ('1.0-c', '<', '1.0-m'), ('1.0-m', '>', '1.0-a1'),
    ('1.0-a1', '<', '1.0-b1'), ('1.0-b1', '<', '1.0-c1'), ('1.0-c1', '>', '1.0-m1'),
    ('1.0-m1', '<', '1.0-x1'), ('1.0-x1', '>', '1.0.a1'), ('1.0.a1', '<', '1.0.b1'),
    ('1.0.b1', '<', '1.0.m1'), ('1.0.m1', '<', '1-0.alpha'), ('1-0.alpha', '=', '1-0-alpha'),
    ('1-0-alpha', '<', '1.0.0-0'), ('1.0.0-0', '=', '1.0.0-0.0'), ('1.0.0-0.0', '<', '1.0-0.1'),
    ('1.0-0.1', '>', '0'), ('0', '=', '0.0'), ('0.0', '=', '0.0.0'), ('0.0.0', '=', '00'),
    ('00', '<', '0.1'), ('0.1', '>', '0.0.1'), ('0.0.1', '>', '0-alpha'),
    ('0-alpha', '<', '0.0-rc1'), ('0.0-rc1', '<', '1.2.3.4.5.6.7.8.9'),
    ('1.2.3.4.5.6.7.8.9', '<', '3.0.0-M1'), ('3.0.0-M1', '<', '3.0.0-M10'),
    ('3.0.0-M10', '>', '3.0.0-M2'), ('3.0.0-M2', '>', '2.22.2'), ('2.22.2', '<', '3.5.2'),
    ('3.5.2', '<', '3.13.0'), ('3.13.0', '>', '3.11.0'), ('3.11.0', '>', '1.0-alpha-10'),
    ('1.0-alpha-10', '>', '1.0-alpha-9'),
]  # fmt: skip

RANGE_VERSIONS = [
    "0.9",
    "1.0-alpha-1",
    "1.0-SNAPSHOT",
    "1.0",
    "1.0.0",
    "1.0.1",
    "1.0-sp",
    "1.1",
    "1.2",
    "1.4.9",
    "1.5-rc1",
    "1.5",
    "1.5.1",
    "1.9",
    "1.99",
    "2.0-alpha-1",
    "2.0-SNAPSHOT",
    "2.0",
    "2.0.0",
    "2.0-jre",
    "2.0.1",
    "2.5",
    "3.0-alpha-1",
    "3.0",
    "3.0.1",
    "3.5",
    "4.0",
    "10.0",
    "1-0",
]

RANGES = [
    ('1.0', '=1.0'), ('[1.0]', '00011000000000000000000000001'),
    ('[1.0,2.0)', '00011111111111111000000000001'), ('[1.0,2.0]', '00011111111111111110000000001'),
    ('(1.0,2.0)', '00000111111111111000000000000'), ('(1.0,2.0]', '00000111111111111110000000000'),
    ('[1.0,)', '00011111111111111111111111111'), ('(1.0,)', '00000111111111111111111111110'),
    ('(,1.0]', '11111000000000000000000000001'), ('(,1.0)', '11100000000000000000000000000'),
    ('[,1.0]', '11111000000000000000000000001'), ('(,)', '11111111111111111111111111111'),
    ('[1.0, 2.0)', '00011111111111111000000000001'),
    ('[ 1.0 , 2.0 ]', '00011111111111111110000000001'),
    ('(,1.0],[1.2,)', '11111000111111111111111111111'),
    ('(,1.0),[1.2,2.0),[3.0,)', '11100000111111111000000111110'),
    ('[1.0,1.5),[1.5,2.0)', '00011111111111111000000000001'),
    ('[1.0,1.5],[1.5,2.0)', '00011111111111111000000000001'), ('[1.0,2.0),[1.5,3.0)', None),
    ('[1.0,),[2.0,3.0)', '00011111111111111111111111111'), ('[1.0)', None), ('(1.0]', None),
    ('(1.0)', None), ('[2.0,1.0)', None), ('[1.0,1.0)', None),
    ('[1.0,1.0]', '00011000000000000000000000001'), ('[1.0,2.0', None), ('[1.0,2.0)x', None),
    ('[1.0,2.0) [3.0,4.0)', '00011111111111111000000111001'), ('[1.0,2.0),3.0', None),
    ('[1.0-alpha-1,1.0)', '01100000000000000000000000000'),
    ('[1.0,2.0-alpha-1)', '00011111111111100000000000001'),
    ('[1.0.RELEASE,2.0)', '00011111111111111000000000001'),
    ('[1.0-SNAPSHOT,1.0]', '00111000000000000000000000001'), ('[1.0,2.0)garbage', None),
    ('1.0-SNAPSHOT', '=1.0-SNAPSHOT'), ('[1.0,2.0,3.0]', '00011111111111111110000000001'),
    ('[1,2)', '00011111111111111000000000001'), ('[0,)', '11111111111111111111111111111'),
    ('[1.0.0,1.0]', '00011000000000000000000000001'),
    ('[1.0,2.0),(2.0,3.0]', '00011111111111111001111100001'),
    ('[1.0,2.0],[2.0,3.0]', '00011111111111111111111100001'),
    ('(1.0,2.0),(2.0,3.0)', '00000111111111111001111000000'), ('[1.0,2.0),[1.0,3.0)', None),
    ('[3.0,4.0),[1.0,2.0)', None),
]  # fmt: skip


def test_registered_for_maven() -> None:
    assert versions.for_ecosystem(Ecosystem.MAVEN) is MAVEN
    assert MAVEN.ecosystem is Ecosystem.MAVEN


@pytest.mark.parametrize(("version", "canonical"), CANONICAL)
def test_canonical_like_maven(version: str, canonical: str) -> None:
    assert MavenVersion(version).canonical == canonical


@pytest.mark.parametrize(("left", "relation", "right"), ORDER)
def test_the_order_of_comparable_version(left: str, relation: str, right: str) -> None:
    expected = {"<": -1, "=": 0, ">": 1}[relation]
    assert MAVEN.compare(left, right) == expected
    assert MAVEN.compare(right, left) == -expected


def test_comparable_version_is_not_transitive() -> None:
    """Comme Maven : 1 < 1a < 1-0.alpha, mais 1 > 1-0.alpha. ``sort_key`` ne lève pas pour
    autant."""
    assert MAVEN.compare("1", "1a") < 0
    assert MAVEN.compare("1a", "1-0.alpha") < 0
    assert MAVEN.compare("1", "1-0.alpha") > 0
    assert sorted(["1-0.alpha", "1a", "1"], key=MAVEN.sort_key)


@pytest.mark.parametrize("text", ["", " ", "1.0 beta", "[1.0]", "1,0", "${v}", "1.0)", "(1"])
def test_refused_versions(text: str) -> None:
    with pytest.raises(InvalidVersion):
        MAVEN.parse(text)


@pytest.mark.parametrize(("spec", "expected"), RANGES)
def test_specifications_like_version_range(spec: str, expected: str | None) -> None:
    if spec == "[1.0,2.0,3.0]":
        expected = None  # une borne haute « 2.0,3.0 » : refusée exprès
    if expected is None:
        with pytest.raises(InvalidConstraint):
            MAVEN.parse_constraint(spec)
        return
    parsed = MAVEN.parse_constraint(spec)
    if expected.startswith("="):
        assert parsed.exact() == expected[1:]
        return
    found = "".join("1" if parsed.contains(MAVEN.parse(v)) else "0" for v in RANGE_VERSIONS)
    assert found == expected


# ---------------------------------------------------------------------------
# Ce que forceupdate en fait
# ---------------------------------------------------------------------------

SATISFIES = [
    # Une version nue n'accepte qu'elle (ou une égale) : sans lockfile, c'est celle de Maven.
    ("1.2.3", "1.2.3", True), ("1.2.3", "1.2.3.0", True), ("1.2.3", "1.2.4", False),
    ("1.2.3", "1.2.2", False), ("[1.2.3]", "1.2.3", True), ("[1.2.3]", "1.2.4", False),
    ("[1.0,2.0)", "1.5", True), ("[1.0,2.0)", "2.0", False), ("[1.0,2.0)", "2.0-alpha-1", True),
    ("(,1.0]", "0.1", True), ("[1.5,)", "99", True), ("(1.0,2.0)", "1.0", False),
    # Gradle : préfixe, la dernière, version stricte, crochets à l'envers.
    ("1.+", "1.9.2", True), ("1.+", "10.0", False), ("1.2.+", "1.2.9", True),
    ("1.2.+", "1.20", False), ("+", "7.0", True), ("latest.release", "3.1", True),
    ("1.7.15!!", "1.7.15", True), ("1.7.15!!", "1.7.16", False), ("]1.0,2.0[", "1.0", False),
    ("]1.0,2.0[", "1.5", True), ("[1.0,2.0[", "2.0", False), ("[1.0,2.0[", "1.0", True),
]  # fmt: skip


@pytest.mark.parametrize(("constraint", "version", "satisfied"), SATISFIES)
def test_satisfies(constraint: str, version: str, satisfied: bool) -> None:
    assert MAVEN.satisfies(constraint, version) is satisfied


@pytest.mark.parametrize(
    ("constraint", "lowest", "exact"),
    [
        ("1.2.3", "1.2.3", "1.2.3"),
        ("31.0.1-jre", "31.0.1-jre", "31.0.1-jre"),
        ("[1.2.3]", "1.2.3", "1.2.3"),
        ("1.2.3!!", "1.2.3", "1.2.3"),
        ("[1.9,2.0)", "1.9", None),
        ("(1.9,2.0)", None, None),
        ("(,2.0)", None, None),
        ("(,1.0],[1.2,)", None, None),
        ("[1.0,1.5),[2.0,)", "1.0", None),
        ("1.+", "1", None),
        ("1.2.+", "1.2", None),
        ("+", None, None),
        ("latest.integration", None, None),
    ],
)
def test_lower_bound_and_exact(constraint: str, lowest: str | None, exact: str | None) -> None:
    assert MAVEN.lower_bound(constraint) == lowest
    assert MAVEN.exact(constraint) == exact


@pytest.mark.parametrize("constraint", ["", "[1.0,2.0", "[1.0)", "${v}", "[2.0,1.0)", "a.+"])
def test_refused_constraints(constraint: str) -> None:
    with pytest.raises(InvalidConstraint):
        MAVEN.parse_constraint(constraint)


@pytest.mark.parametrize(
    ("version", "prerelease"),
    [
        ("1.0-alpha-1", True), ("1.0-beta1", True), ("2.0-M1", True), ("2.0.0-RC1", True),
        ("2.0.CR1", True), ("1.0-SNAPSHOT", True), ("4.0.0-alpha.11", True), ("2.0-ea", True),
        ("2.0-dev", True), ("2.0-preview", True), ("2.0-pre", True), ("1.0", False),
        ("31.0.1-jre", False), ("5.4.0.Final", False), ("1.0-sp1", False), ("1.0.RELEASE", False),
        ("9.4.51.v20230217", False), ("1.0-incubating", False),
    ],
)  # fmt: skip
def test_prereleases(version: str, prerelease: bool) -> None:
    assert MAVEN.is_prerelease(version) is prerelease


def test_flavors_are_kept() -> None:
    """De 31.0.1-jre, Guava monte en -jre, jamais en -android ; sans variante, tout va."""
    published = ["31.1-android", "31.1-jre", "32.0.0-android", "32.0.0-jre", "33.0-rc1-jre"]
    assert MAVEN.latest(published, "31.0.1-jre") == "32.0.0-jre"
    assert MAVEN.latest(published, "31.0.1-android") == "32.0.0-android"
    assert MAVEN.latest(published) == "32.0.0-jre"  # le mot « jre » vient après « android »
    assert MAVEN.candidates(["19.0", "33.0-android", "33.0-jre"], "18.0") == [
        "19.0",
        "33.0-android",
        "33.0-jre",
    ]
    assert MAVEN.candidates(["10.0.0", "9.4.52.v20230823"], "9.4.51.v20230217") == [
        "10.0.0",
        "9.4.52.v20230823",
    ]
    assert not MAVEN.compatible("31.0.1-jre", "32.0.0-android")
    assert MAVEN.compatible("31.0.1-jre", "40.0")


@pytest.mark.parametrize(
    ("current", "target", "gap"),
    [
        ("2.14.1", "2.15.0", Gap.MINOR),
        ("2.14.1", "2.14.2", Gap.PATCH),
        ("2.14.1", "3.0.0", Gap.MAJOR),
        ("30.1-jre", "30.1.1-jre", Gap.PATCH),
        ("30.1-jre", "33.7.2-jre", Gap.MAJOR),
        ("23", "40", Gap.MAJOR),
        ("1.0-alpha-1", "1.0", Gap.MAJOR),
        ("5.3.17", "5.3.17.RELEASE", None),
        ("4.12", "4.13.2", Gap.MINOR),
    ],
)
def test_gap(current: str, target: str, gap: Gap | None) -> None:
    assert MAVEN.gap(current, target) is gap


def test_max_satisfying_without_prereleases() -> None:
    published = ["1.9", "1.10.0", "1.15.0", "2.0-alpha-1", "2.0"]
    assert MAVEN.max_satisfying("[1.9,2.0)", published) == "1.15.0"
    assert MAVEN.max_satisfying("1.9", published) == "1.9"
    assert MAVEN.max_satisfying("1.+", published) == "1.15.0"
