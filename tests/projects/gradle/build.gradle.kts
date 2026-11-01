plugins {
    java
    id("org.springframework.boot") version "2.6.6" apply false
    alias(libs.plugins.versions)
}

val commonsTextVersion = "1.9"

dependencies {
    implementation(libs.guava)
    implementation("org.apache.commons:commons-text:$commonsTextVersion")
    testImplementation(libs.junit)
    implementation(platform("com.fasterxml.jackson:jackson-bom:2.13.0"))
    // Sa version vient de la plateforme (le BOM) : pas vérifiable.
    implementation("com.fasterxml.jackson.core:jackson-databind")
}
