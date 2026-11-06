import hudson.util.PluginServletFilter
import jakarta.servlet.Filter
import jakarta.servlet.FilterChain
import jakarta.servlet.FilterConfig
import jakarta.servlet.ServletRequest
import jakarta.servlet.ServletResponse
import jakarta.servlet.http.HttpServletRequest
import jakarta.servlet.http.HttpServletResponse
import jenkins.model.Jenkins

// Core forces the wizard at / only. A saved login target can point at /manage/appearance/.
// Route browser management pages to the wizard until setup completes; do not change auth or saved data.
PluginServletFilter.addFilter(new Filter() {
    void init(FilterConfig config) {}

    void doFilter(ServletRequest request, ServletResponse response, FilterChain chain) {
        if (request instanceof HttpServletRequest && response instanceof HttpServletResponse) {
            def path = request.requestURI.substring(request.contextPath.length())
            def managementPage = path == '/manage' || path.startsWith('/manage/')
            def htmlPage = request.getHeader('Accept')?.contains('text/html')
            def j = Jenkins.get()
            if (request.method == 'GET' && managementPage && htmlPage && !j.installState.isSetupComplete()) {
                j.checkPermission(Jenkins.ADMINISTER)
                response.sendRedirect(request.contextPath + '/setupWizard/')
                return
            }
        }
        chain.doFilter(request, response)
    }

    void destroy() {}
})
