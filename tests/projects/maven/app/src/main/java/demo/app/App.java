package demo.app;

import demo.lib.Greeter;

public final class App {
    public static void main(String[] args) {
        System.out.println(new Greeter().greet("Maven"));
    }
}
