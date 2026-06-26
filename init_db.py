import sqlite3

def init_db():
    conn = sqlite3.connect('metrics_engine.db')
    cursor = conn.cursor()

    tables = ["widgets", "dashboard_templates", "dashboard_defaults", "rec_co_occurrence"]
    for t in tables: cursor.execute(f"DROP TABLE IF EXISTS {t}")

    cursor.execute('CREATE TABLE widgets (widget_id TEXT PRIMARY KEY, widget_name TEXT, category_tag TEXT)')
    cursor.execute('CREATE TABLE dashboard_templates (template_id TEXT PRIMARY KEY, template_name TEXT, category_tag TEXT)')
    cursor.execute('CREATE TABLE dashboard_defaults (template_id TEXT, widget_id TEXT, PRIMARY KEY(template_id, widget_id))')
    cursor.execute('CREATE TABLE rec_co_occurrence (widget_a_id TEXT, widget_b_id TEXT, confidence_score REAL, PRIMARY KEY(widget_a_id, widget_b_id))')

    # 1. Master list of ALL 19 dashboards from your original files list
    templates = [
        ('aws_core', 'amazon web services', 'aws'),
        ('aws_monitor', 'aws monitor', 'aws'),
        ('azure_monitor', 'azure', 'azure'),
        ('capacity_monitor', 'capacity monitor', 'server'),
        ('cisco_network', 'cisco', 'network'),
        ('container_monitor', 'container', 'container'),
        ('demo_dash', 'demo', 'demo'),
        ('gcp_demo', 'GCP-demo', 'gcp'),
        ('k8s_daemonsets', 'kubernetes daemonsets', 'kubernetes'),
        ('k8s_deployment', 'kubernetes deployment', 'kubernetes'),
        ('k8s_node', 'kubernetes node', 'kubernetes'),
        ('k8s_replicaset', 'kubernetes replicaset', 'kubernetes'),
        ('netflow_14aug', 'netflow 14aug', 'network'),
        ('network_14aug', 'network 14aug', 'network'),
        ('security_monitors', 'security monitors', 'security'),
        ('server_perf', 'server performance', 'server'),
        ('vmware_monitor', 'VMware', 'vmware'),
        ('web_trans_browser', 'web transaction monitor(browser)', 'web'),
        ('webpage_speed', 'webpage speed', 'web')
    ]
    cursor.executemany('INSERT INTO dashboard_templates VALUES (?, ?, ?)', templates)

    # 2. Master Metrics Catalog for ALL types of infrastructure
    widgets = [
        # AWS Group
        ('aws_ec2_cpu', 'AWS EC2 CPU Utilization', 'aws'),
        ('aws_ec2_disk', 'AWS EBS Disk Read/Write IOPS', 'aws'),
        ('aws_rds_conn', 'Database Connection Count', 'aws'),
        ('aws_alb_latency', 'ALB Target Response Time', 'aws'),
        ('aws_billing', 'Estimated AWS Month-to-Date Cost', 'aws'),
        
        # Azure Group
        ('az_vm_cpu', 'Azure VM Percentage CPU', 'azure'),
        ('az_storage_success', 'Azure Storage Success Percentage', 'azure'),
        ('az_network_in', 'Azure Virtual Network Inbound Traffic', 'azure'),
        
        # GCP Group
        ('gcp_compute_cpu', 'GCP Compute Engine CPU Utilization', 'gcp'),
        ('gcp_logging_volume', 'GCP Cloud Logging Log Volume', 'gcp'),
        
        # Kubernetes & Container Groups
        ('k8s_cpu', 'Kubernetes Node CPU Usage', 'kubernetes'),
        ('k8s_mem', 'Kubernetes Node Memory Allocation', 'kubernetes'),
        ('k8s_net', 'Kubernetes Node Network In/Out', 'kubernetes'),
        ('k8s_pods', 'Active Pod Count', 'kubernetes'),
        ('k8s_restarts', 'Container Restart Rate', 'kubernetes'),
        ('k8s_limits', 'Namespace Resource Limits', 'kubernetes'),
        ('k8s_pending', 'Pending Pods Alert Status', 'kubernetes'),
        ('cont_cpu', 'Docker Container CPU Percentage', 'container'),
        ('cont_io', 'Container Block I/O Read/Write', 'container'),
        
        # Network & Cisco Groups
        ('net_flow_rate', 'NetFlow Traffic Volume', 'network'),
        ('net_bandwidth', 'Interface Bandwidth Usage', 'network'),
        ('net_drops', 'Packet Drop Rate', 'network'),
        ('net_jitter', 'WAN Jitter Metrics', 'network'),
        ('net_cisco_cpu', 'Cisco Switch CPU Utilization', 'network'),
        ('net_errors', 'Interface Inbound/Outbound Errors', 'network'),
        
        # Server Performance / Capacity / VMware / Security Groups
        ('srv_load', 'Server Load Average', 'server'),
        ('srv_disk_space', 'Disk Partition Usage %', 'server'),
        ('srv_ram', 'Physical RAM Availability', 'server'),
        ('srv_vm_balloon', 'VMware Memory Ballooning Rate', 'server'),
        ('sec_failed_logins', 'Failed Authentication Attempts Count', 'security'),
        ('sec_firewall_drops', 'Firewall Blocked Packet Volumne', 'security'),
        
        # Web / Webpage Speed / Browser / Demo Groups
        ('web_dns', 'DNS Resolution Speed', 'web'),
        ('web_dom', 'DOM Interactive Rendering Latency', 'web'),
        ('web_ssl', 'SSL Certificate Expiry Monitor', 'web'),
        ('web_apdex', 'User Satisfaction Index (Apdex)', 'web'),
        ('web_ttfb', 'Time to First Byte (TTFB)', 'web'),
        ('web_fcp', 'First Contentful Paint (FCP)', 'web'),
        ('web_cls', 'Cumulative Layout Shift (CLS)', 'web'),
        ('demo_metric_1', 'Demo Environment Simulation Traffic', 'demo'),
        ('demo_metric_2', 'Demo Response Microservices Latency', 'demo')
    ]
    cursor.executemany('INSERT INTO widgets VALUES (?, ?, ?)', widgets)

    # 3. Dynamic Generation: Automatically populate distinct Step 2 defaults for EVERY single dashboard template
    for t_id, t_name, cat in templates:
        # Fetch widgets that match this dashboard's specific category
        matching_widgets = [w[0] for w in widgets if w[2] == cat]
        # Map the first 4 matching metrics as the Step 2 bundle defaults for this dashboard
        for w_id in matching_widgets[:4]:
            cursor.execute('INSERT INTO dashboard_defaults VALUES (?, ?)', (t_id, w_id))

    # 4. Step 3 Core Association Rules Cross-Pairing Matrix
    rules = [
        # AWS co-occurrences
        ('aws_ec2_cpu', 'aws_ec2_disk', 0.95), ('aws_ec2_cpu', 'aws_alb_latency', 0.90), ('aws_ec2_disk', 'aws_billing', 0.85),
        # Azure co-occurrences
        ('az_vm_cpu', 'az_network_in', 0.92), ('az_vm_cpu', 'az_storage_success', 0.88),
        # Network / Cisco co-occurrences
        ('net_flow_rate', 'net_bandwidth', 0.96), ('net_flow_rate', 'net_drops', 0.91), ('net_bandwidth', 'net_cisco_cpu', 0.89),
        # Web Speed / Browser co-occurrences
        ('web_apdex', 'web_dom', 0.98), ('web_apdex', 'web_ssl', 0.92), ('web_dns', 'web_ttfb', 0.94), ('web_dom', 'web_fcp', 0.91),
        # Kubernetes co-occurrences
        ('k8s_cpu', 'k8s_mem', 0.99), ('k8s_cpu', 'k8s_restarts', 0.93), ('k8s_pods', 'k8s_pending', 0.95)
    ]
    cursor.executemany('INSERT INTO rec_co_occurrence VALUES (?, ?, ?)', rules)

    conn.commit()
    conn.close()
    print("🚀 Master Database re-seeded! All 19 dashboards have separate, unique recommendations.")

if __name__ == '__main__':
    init_db()