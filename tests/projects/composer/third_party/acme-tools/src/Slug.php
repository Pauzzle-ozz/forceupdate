<?php

namespace Acme\Tools;

final class Slug
{
    public static function of(string $text): string
    {
        return strtolower(trim((string) preg_replace('/[^A-Za-z0-9]+/', '-', $text), '-'));
    }
}
