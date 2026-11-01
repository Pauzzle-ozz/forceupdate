namespace App.Tests;

public class GreeterTests
{
    [Xunit.Fact]
    public void SaysHello() => Xunit.Assert.Equal("Bonjour Ada", Greeter.Hello("Ada"));
}
