<?php

namespace Demo;

use Acme\Tools\Slug;
use GuzzleHttp\Client;
use Monolog\Handler\StreamHandler;
use Monolog\Logger;

final class App
{
    public function run(string $url): string
    {
        $logger = new Logger('demo');
        $logger->pushHandler(new StreamHandler('php://stderr'));
        $logger->info('Lecture de ' . $url);

        $response = (new Client())->get($url);

        return Slug::of((string) $response->getBody());
    }
}
