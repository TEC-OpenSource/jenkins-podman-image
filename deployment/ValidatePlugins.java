import java.io.*;
import java.net.*;
import java.nio.file.*;
import java.util.*;
import java.util.jar.*;

/** Validate using Jenkins' own VersionNumber, not lexical/semver comparison. */
class ValidatePlugins {
    public static void main(String[] args) throws Exception {
        if (args.length != 3) throw new IllegalArgumentException("WAR PLUGIN_DIRECTORY EXPECTED_CORE");
        Path versions = Files.createTempFile("jenkins-version-number-", ".jar");
        try (JarFile war = new JarFile(args[0])) {
            String core = war.getManifest().getMainAttributes().getValue("Jenkins-Version");
            if (!args[2].equals(core)) throw new IllegalStateException("Unexpected Jenkins core: " + core);
            var entry = war.stream().filter(e -> e.getName().matches("WEB-INF/lib/version-number-.*\\.jar")).findFirst().orElseThrow();
            try (var input = war.getInputStream(entry)) { Files.copy(input, versions, StandardCopyOption.REPLACE_EXISTING); }
        }
        try (var loader = new URLClassLoader(new URL[] {versions.toUri().toURL()})) {
            Class<?> number = loader.loadClass("hudson.util.VersionNumber");
            var constructor = number.getConstructor(String.class);
            var older = number.getMethod("isOlderThan", number);
            Map<String, Attributes> plugins = new TreeMap<>();
            try (var paths = Files.list(Path.of(args[1]))) {
                for (Path path : paths.filter(p -> p.toString().endsWith(".jpi") || p.toString().endsWith(".hpi")).toList()) {
                    try (JarFile jar = new JarFile(path.toFile())) {
                        Attributes manifest = jar.getManifest().getMainAttributes();
                        String id = manifest.getValue("Short-Name");
                        if (id == null || manifest.getValue("Plugin-Version") == null ||
                            !(path.getFileName().toString().equals(id + ".jpi") || path.getFileName().toString().equals(id + ".hpi")) ||
                            plugins.putIfAbsent(id, manifest) != null) {
                            throw new IllegalStateException("Invalid/duplicate plugin manifest: " + path);
                        }
                    }
                }
            }
            for (var plugin : plugins.entrySet()) {
                String required = plugin.getValue().getValue("Jenkins-Version");
                if (required == null || (boolean) older.invoke(constructor.newInstance(args[2]), constructor.newInstance(required))) {
                    throw new IllegalStateException(plugin.getKey() + " requires Jenkins " + required);
                }
                String dependencies = plugin.getValue().getValue("Plugin-Dependencies");
                if (dependencies == null) continue;
                for (String dependency : dependencies.split(",")) {
                    String[] fields = dependency.trim().split(";");
                    String[] ref = fields[0].split(":", 2);
                    Attributes target = plugins.get(ref[0]);
                    boolean optional = Arrays.asList(fields).contains("resolution:=optional");
                    if (target == null && optional) continue;
                    if (ref.length != 2 || target == null || (boolean) older.invoke(
                        constructor.newInstance(target.getValue("Plugin-Version")), constructor.newInstance(ref[1]))) {
                        throw new IllegalStateException(plugin.getKey() + " has unsatisfied dependency: " + dependency);
                    }
                }
            }
            System.out.println("Validated core requirements and dependency versions for " + plugins.size() + " plugins");
        } finally { Files.deleteIfExists(versions); }
    }
}
