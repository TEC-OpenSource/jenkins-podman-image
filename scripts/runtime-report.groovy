// Run in Manage Jenkins > Script Console with ADMINISTER; contains no credentials.
import jenkins.model.Jenkins
import hudson.model.User
def j = Jenkins.get()
assert System.getProperty('java.specification.version') == '25'
println("core=${Jenkins.VERSION}")
assert !j.pluginManager.failedPlugins
j.pluginManager.plugins.each { p ->
    assert p.active : "Not active: ${p.shortName}"
    println("${p.shortName}:${p.version} active")
}
assert !j.authorizationStrategy.rootACL.hasPermission2(Jenkins.ANONYMOUS2, Jenkins.ADMINISTER)
assert !j.authorizationStrategy.rootACL.hasPermission2(Jenkins.ANONYMOUS2, Jenkins.READ)
println("runtime=${System.getProperty('java.runtime.version')}")
println("realm=${j.securityRealm.class.name}")
println("authorization=${j.authorizationStrategy.class.name}")
println("users=${User.getAll().size()}, executors=${j.numExecutors}")
println('This report does not test EAI/Oracle/organization policy or existing user sessions.')
