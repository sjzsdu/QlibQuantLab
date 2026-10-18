import type {ReactNode} from 'react';
import Link from '@docusaurus/Link';
import Layout from '@theme/Layout';

const ports = [
  ['数据库', 'DatabasePort', 'SQLAlchemy 2.0 async / SQLite（本机零依赖）'],
  ['缓存', 'CachePort', 'Redis / 内存实现'],
  ['消息队列', 'QueuePort', 'RabbitMQ / 内存实现'],
  ['对象存储', 'StoragePort', '本地卷 / S3 兼容（MinIO）'],
  ['认证', 'AuthProviderPort', 'Mock（4 profile）/ Casdoor'],
  ['审计', 'AuditPort', '审计表 + 结构化日志'],
  ['计算', 'ComputePort', 'stub 合成 / qlib 取数 + 自研模拟器'],
];

const enforced = [
  ['业务层禁止 import SDK', 'redis / pika / aio_rabbit / boto3 / socketio / qlib / casdoor 出现在 ports、services、api 层即测试失败。'],
  ['禁止硬编码主机名 / IP', '出现主机名或 IP 字面量、或在 config.py 之外读环境变量，即测试失败。'],
  ['多租户不可绕过', '15 张业务表必须有非空 org_id 且被索引覆盖。'],
  ['qlib 只在一个进程', '架构测试 + 单测双重断言：qlib 只允许出现在 worker 进程的两个模块里。'],
  ['端口全覆盖', 'container.py 是唯一把端口换成实现的地方，新增适配器必须在装配点登记。'],
];

export default function Architecture(): ReactNode {
  return (
    <Layout
      title="架构与边界"
      description="QlibQuantLab 的架构：Ports & Adapters 七个端口、多租户 OrgScope、qlib 仅在 worker 进程的物理边界，以及模式 A / 模式 B 两种部署形态。">
      <header className="qql-hero" style={{padding: '3.5rem 0 3rem'}}>
        <div className="qql-container">
          <span className="qql-eyebrow">架构</span>
          <h1 className="qql-hero__title" style={{fontSize: 'clamp(1.9rem, 4vw, 2.7rem)'}}>
            代码边界画在哪里，运维边界才能守住
          </h1>
          <p className="qql-hero__sub" style={{maxWidth: '62ch'}}>
            业务代码只依赖抽象端口，SDK 只出现在适配器里；qlib 依赖 Redis 与 RabbitMQ
            且是进程单例，因此它只活在一个容器里，而 Web 进程只是它的客户端。
          </p>
        </div>
      </header>

      <section className="qql-section">
        <div className="qql-container">
          <span className="qql-eyebrow">部署形态</span>
          <h2 className="qql-h2">一次请求会碰到哪些进程</h2>
          <p className="qql-lead">
            实线是同步调用，虚线表示「只在这个进程里存在」。Web 侧链路完全不经过 qlib。
          </p>

          <div className="qql-arch" style={{marginTop: '1.75rem'}}>
            <div className="qql-arch__row">
              <div className="qql-arch__node">
                <b>浏览器</b>
                <code>1440×900 / 移动端</code>
              </div>
              <div className="qql-arch__node">
                <b>Traefik（模式 B）</b>
                <code>labels 暴露，应用不感知</code>
              </div>
            </div>
            <div className="qql-arch__arrow">↓</div>
            <div className="qql-arch__row">
              <div className="qql-arch__node qql-arch__node--emph">
                <b>frontend</b>
                <code>Next.js 15 · :3000</code>
              </div>
              <div className="qql-arch__node qql-arch__node--emph">
                <b>backend</b>
                <code>FastAPI · :8000</code>
              </div>
            </div>
            <div className="qql-arch__arrow">↓ 端口（Ports &amp; Adapters）</div>
            <div className="qql-arch__row">
              <div className="qql-arch__node">
                <b>PostgreSQL</b>
                <code>业务表 + 审计</code>
              </div>
              <div className="qql-arch__node">
                <b>Redis</b>
                <code>缓存 / 会话辅助</code>
              </div>
              <div className="qql-arch__node">
                <b>对象存储</b>
                <code>本地卷 / S3</code>
              </div>
              <div className="qql-arch__node">
                <b>RabbitMQ</b>
                <code>任务队列</code>
              </div>
            </div>
            <div className="qql-arch__arrow">↓ 任务入队</div>
            <div className="qql-arch__row">
              <div className="qql-arch__node qql-arch__node--worker">
                <b>worker（唯一 import qlib 的进程）</b>
                <code>Python 3.11 · QLIB_WORKER_CONCURRENCY=1</code>
              </div>
              <div className="qql-arch__node qql-arch__node--worker">
                <b>qlib-server</b>
                <code>WS :9710 · 自建镜像</code>
              </div>
            </div>
            <p className="qql-arch__legend">
              虚线框 = qlib 生态。API 镜像（Python 3.12）<b>物理不包含 qlib</b>
              ；并发度必须为 1，因为 qlib 是进程单例且硬依赖 Redis + RabbitMQ。
            </p>
          </div>
        </div>
      </section>

      <section className="qql-section qql-section--surface">
        <div className="qql-container">
          <span className="qql-eyebrow">Ports &amp; Adapters</span>
          <h2 className="qql-h2">七个端口，一个装配点</h2>
          <p className="qql-lead">
            业务代码只认接口：换数据库、换 IdP、换对象存储都不动业务层。<code>container.py</code>
            是全仓唯一把端口换成实现的地方。
          </p>
          <div style={{overflowX: 'auto', marginTop: '1.5rem'}}>
            <table>
              <thead>
                <tr>
                  <th>端口</th>
                  <th>接口</th>
                  <th>实现</th>
                </tr>
              </thead>
              <tbody>
                {ports.map(([name, api, impl]) => (
                  <tr key={api}>
                    <td>{name}</td>
                    <td>
                      <code>{api}</code>
                    </td>
                    <td>{impl}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section className="qql-section">
        <div className="qql-container">
          <span className="qql-eyebrow">强制执行</span>
          <h2 className="qql-h2">约定不靠自觉，靠测试</h2>
          <p className="qql-lead">
            <code>backend/tests/architecture/</code> 用 AST 扫描代码，违反约定就是红的。
          </p>
          <div className="qql-grid qql-grid--2" style={{marginTop: '1.5rem'}}>
            {enforced.map(([title, body]) => (
              <div key={title} className="qql-card">
                <h3>{title}</h3>
                <p>{body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="qql-section qql-section--surface">
        <div className="qql-container">
          <span className="qql-eyebrow">多租户</span>
          <h2 className="qql-h2">org_id 只来自会话</h2>
          <div className="qql-grid qql-grid--2" style={{marginTop: '1.5rem'}}>
            <div className="qql-card">
              <h3>边界怎么落</h3>
              <p>
                <code>OrgScope</code> 由会话解析，<code>BaseRepo</code>{' '}
                在每条查询上强制拼 <code>org_id</code> 过滤；跨组织的读、改、删统一返回{' '}
                <code>404</code>，不通过 403 泄露资源是否存在。
              </p>
            </div>
            <div className="qql-card">
              <h3>可见性怎么叠</h3>
              <p>
                项目与因子在组织内还有一层可见性（private / org / public）。默认私有，切换可见性属于高危操作：仅
                admin，且必须带 <code>?confirm=true</code>。
              </p>
            </div>
            <div className="qql-card">
              <h3>认证为什么可插拔</h3>
              <p>
                会话是平台自己签发的 JWT cookie，IdP 令牌只在后端留存。换 Casdoor
                时只改环境变量（<code>AUTH_PROVIDER</code> 等），前后端代码零改动；生产环境若仍是{' '}
                <code>mock</code> 会拒绝启动。
              </p>
            </div>
            <div className="qql-card">
              <h3>可追溯怎么串</h3>
              <p>
                统一响应信封 <code>{'{code, message, data, request_id}'}</code>；
                <code>request_id</code> 同时落在响应头 <code>X-Request-ID</code>
                、结构化日志与审计表，可以三方对照。
              </p>
            </div>
          </div>
        </div>
      </section>

      <section className="qql-section">
        <div className="qql-container">
          <span className="qql-eyebrow">两种部署形态</span>
          <h2 className="qql-h2">模式 A 自包含 / 模式 B 复用基础设施</h2>
          <div className="qql-grid qql-grid--2" style={{marginTop: '1.5rem'}}>
            <div className="qql-card">
              <h3>模式 A · 自包含</h3>
              <p>
                一份 <code>docker-compose.yml</code> 起七个服务（前端 / 后端 / worker / 迁移 /
                pg / redis / rabbitmq），适合开发与评估。qlib 链路由{' '}
                <code>--profile qlib</code> 选择性启动。
              </p>
            </div>
            <div className="qql-card">
              <h3>模式 B · 复用基础设施</h3>
              <p>
                只起业务容器，数据库 / 缓存 / MQ / 对象存储指向外部实例；容器挂在{' '}
                <code>internal</code>（不出网）+ <code>traefik</code> 网络，暴露只经 compose
                层的 Traefik labels。
              </p>
            </div>
          </div>
          <div className="qql-actions" style={{marginTop: '1.75rem'}}>
            <Link className="qql-btn qql-btn--ghost" to="/docs/deployment">
              部署细节与环境变量 →
            </Link>
            <Link className="qql-btn qql-btn--ghost" to="/docs/quickstart">
              先在本机跑起来 →
            </Link>
          </div>
        </div>
      </section>
    </Layout>
  );
}
