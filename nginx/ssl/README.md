# SSL 证书目录

此目录存放 HTTPS 证书文件。**不提交到 git**（已在 .gitignore 中配置）。

## 开发/测试：生成自签名证书

```bash
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout nginx/ssl/key.pem \
  -out nginx/ssl/cert.pem \
  -subj "/CN=localhost"
```

## 生产：使用 Let's Encrypt 免费证书

```bash
# 安装 certbot
apt install certbot

# 申请证书（先停 nginx/80 端口，或用 webroot 模式）
certbot certonly --standalone -d your-domain.com

# 证书路径
# 证书：/etc/letsencrypt/live/your-domain.com/fullchain.pem
# 私钥：/etc/letsencrypt/live/your-domain.com/privkey.pem

# 复制到项目目录
cp /etc/letsencrypt/live/your-domain.com/fullchain.pem nginx/ssl/cert.pem
cp /etc/letsencrypt/live/your-domain.com/privkey.pem nginx/ssl/key.pem
```

## 文件命名

- `cert.pem` — 证书链（包含中间证书）
- `key.pem` — 私钥（严格保密，chmod 600）
