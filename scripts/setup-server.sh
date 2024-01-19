#!/bin/bash

WORKDIR=$(pwd)

# Install docker and git
yum install -y docker git
usermod -a -G docker ec2-user
systemctl enable docker.service
systemctl start docker.service

# Setup docker compose plugin
mkdir -p /usr/local/lib/docker/cli-plugins
curl -SL https://github.com/docker/compose/releases/download/v2.24.1/docker-compose-linux-x86_64 -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# Clone repo
git clone https://github.com/kavichu/aws-web-server-cdk.git /home/ec2-user/code

# Generate self signed certificate
mkdir /home/ec2-user/code/certs
cd /home/ec2-user/code/certs
openssl genrsa -des3 -passout pass:x -out server.pass.key 2048
openssl rsa -passin pass:x -in server.pass.key -out server.key
rm server.pass.key
openssl req -new -key server.key -out server.csr \
    -subj "/C=BR/ST=Sao Paulo/L=SP/O=Aratiri/OU=IT Department/CN=aratiri.dev"
openssl x509 -req -days 365 -in server.csr -signkey server.key -out server.crt

cd $WORKDIR

# Create script to start the web application using systemd
cat > /root/start-nginx.sh << __EOF__
#!/bin/bash
cd /home/ec2-user/code
docker compose up -d
__EOF__

# Add execution permission to script
chmod +x /root/start-nginx.sh

# Create systemd service
cat > /etc/systemd/system/docker-compose-nginx.service << __EOF__
[Unit]
Description=Run nginx web server using docker compose
After=multi-user.target

[Service]
ExecStart=/usr/bin/bash /root/start-nginx.sh
Type=simple

[Install]
WantedBy=multi-user.target
__EOF__

# Enable and start service
systemctl enable docker-compose-nginx
systemctl start docker-compose-nginx
