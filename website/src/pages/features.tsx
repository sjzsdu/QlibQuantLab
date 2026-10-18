import type {ReactNode} from 'react';
import Link from '@docusaurus/Link';
import Layout from '@theme/Layout';

type Item = {
  title: string;
  problem: string;
  detail: string;
  to?: string;
  toLabel?: string;
};

type Group = {
  id: string;
  eyebrow: string;
  title: string;
  lead: string;
  items: Item[];
};

const groups: Group[] = [
  {
    id: 'research',
    eyebrow: '研究资产',
    title: '项目 · 数据 · 因子',
    lead: '研究的起点不是代码，而是「谁的数据、谁的策略、谁能看到」。这一组能力把这三件事在落库前就定下来。',
    items: [
      {
        title: '项目（Projects）',
        problem: '同一个平台里跑多个研究课题，内容不该互相看见。',
        detail:
          '新建项目默认私有，可见性可切到 private / org / public；成员按 viewer / researcher / admin 授权；删除与可见性变更都需要二次确认。',
        to: '/docs/guides/projects',
        toLabel: '项目指南',
      },
      {
        title: '数据集与授权台账（Data）',
        problem: '数据能不能用、能用到什么程度，通常只存在某个人脑子里。',
        detail:
          '数据源先登记，再登记授权台账（用途、是否允许再分发、失效日期、凭证 URI），数据集必须挂一份有效台账才能创建；导入走后台任务，进度在任务中心轮询；标的、股票池、交易日历与 OHLCV 预览可直接只读解析。',
        to: '/docs/concepts',
      },
      {
        title: '因子库（Factors）',
        problem: '因子散落在 notebook 里，改了什么、谁改的、什么时候改的说不清。',
        detail:
          '表达式落库前做静态校验（字段 / 函数白名单 + 语法），表达式一变更版本号即 +1；可提交因子计算任务做 IC 预览，日度 rank-IC 曲线降采样到 1500 点以内。',
        to: '/docs/guides/factors',
        toLabel: '因子指南',
      },
    ],
  },
  {
    id: 'compute',
    eyebrow: '计算',
    title: '模型 · 回测 · 任务中心',
    lead: '所有需要算力的动作都是后台任务：提交后可以离开页面，回来仍能看到状态、日志与产物。',
    items: [
      {
        title: '模型与训练（Models）',
        problem: '训练结果对不上号：这版指标到底是哪个因子、哪段区间跑出来的？',
        detail:
          '创建模型时引用因子库并**快照**表达式，训练任务绑定数据集与切分配置；算法目录由后端下发，避免前端硬编码选型。',
        to: '/docs/concepts',
      },
      {
        title: '回测（Backtests）',
        problem: '回测报告好看，但费用假设、数据区间、股票池都没写清楚，等于无法复核。',
        detail:
          '佣金、滑点、冲击成本**三件套必填**，缺一项即 422；结果带四标注（数据区间与来源、引擎、费用、局限性），净值曲线降采样展示，报告与持仓明细可导出 CSV 并记审计。',
        to: '/docs/guides/backtests',
        toLabel: '回测指南',
      },
      {
        title: '任务中心（Jobs）',
        problem: '长任务失败时只看到「失败了」，不知道卡在哪一步。',
        detail:
          '数据导入、因子计算、训练、回测统一入队；可看增量日志与当前状态，queued 直接取消、running 协作式取消，失败可按原 payload 重试。',
        to: '/docs/concepts',
      },
    ],
  },
  {
    id: 'governance',
    eyebrow: '治理',
    title: '多租户 · RBAC · 审计 · 合规',
    lead: '这部分是「给团队用」和「自己用」的分水岭，也是量化研究平台最容易被忽略的一半。',
    items: [
      {
        title: '多租户隔离',
        problem: '组织之间的数据必须互不可见，且不能靠每个开发者自觉。',
        detail:
          '15 张业务表强制非空 org_id 且被索引覆盖（架构测试强制）；org_id 只来自会话，仓储层强制拼过滤，跨组织读改删统一返回 404，不泄露存在性。',
        to: '/architecture',
      },
      {
        title: 'RBAC 权限矩阵',
        problem: '「谁能删项目」这种问题不该靠口头约定。',
        detail:
          '四种角色（admin / researcher / viewer / auditor）对应 29 项权限；高危动作（删除、发布、可见性切换、授权台账变更）仅 admin 且需二次确认；前端调用 /api/v1/me/permissions 渲染。',
        to: '/docs/concepts#角色与权限',
      },
      {
        title: '审计留痕',
        problem: '出了问题要能回答「谁、什么时候、对什么做了什么」。',
        detail:
          '写入、导出、删除都记审计；request_id 同时出现在响应头、结构化日志与审计表，三方可串联；审计列表可按动作筛选并导出 CSV（导出本身也记一条审计）。',
        to: '/docs/concepts',
      },
      {
        title: '合规与法务',
        problem: '量化平台对外必须讲清楚「不构成投资建议」，而且不能每个页面各写一份。',
        detail:
          '法务文案由后端 /api/v1/legal/* 统一提供，站点法务页与产品内页面同源生成；首页与文档页常驻风险提示。',
        to: '/legal/disclaimer',
      },
    ],
  },
];

const notIncluded = [
  ['公开在线 demo', '当前 Mock 认证可一键切角色（含 admin），公开即风险；用脱敏截图代替。'],
  ['多语言站点', 'P0 只做中文；i18n 结构与配置已就位，英文是后续的事。'],
  ['文档版本化', '当前 0.1.0 且无 release tag，只维护 latest；1.0 再开版本切换器。'],
  ['博客 / 社区论坛', '没有稳定内容的博客是开源站的常见笑话，等有文章再上线。'],
];

export default function Features(): ReactNode {
  return (
    <Layout
      title="能力"
      description="QlibQuantLab 的能力清单：项目、数据与授权台账、因子库、模型训练、回测、任务中心，以及多租户、RBAC、审计与合规治理。">
      <header className="qql-hero" style={{padding: '3.5rem 0 3rem'}}>
        <div className="qql-container">
          <span className="qql-eyebrow">能力</span>
          <h1 className="qql-hero__title" style={{fontSize: 'clamp(1.9rem, 4vw, 2.7rem)'}}>
            一次研究需要的三组能力
          </h1>
          <p className="qql-hero__sub" style={{maxWidth: '62ch'}}>
            为团队提供多组织数据与策略隔离、可插拔认证与审计留痕；训练与回测跑在独立 worker
            容器中，Web 进程永不 <code>import qlib</code>，让研究过程可复现、可追溯。
          </p>
        </div>
      </header>

      {groups.map((g, i) => (
        <section
          key={g.id}
          id={g.id}
          className={i % 2 === 1 ? 'qql-section qql-section--surface' : 'qql-section'}>
          <div className="qql-container">
            <span className="qql-eyebrow">{g.eyebrow}</span>
            <h2 className="qql-h2">{g.title}</h2>
            <p className="qql-lead">{g.lead}</p>
            <div className="qql-grid qql-grid--3" style={{marginTop: '1.75rem'}}>
              {g.items.map((item) => (
                <article key={item.title} className="qql-card">
                  <h3>{item.title}</h3>
                  <p style={{marginBottom: '0.6rem'}}>
                    <strong>解决</strong>：{item.problem}
                  </p>
                  <p>{item.detail}</p>
                  {item.to && (
                    <Link className="qql-card__meta" to={item.to}>
                      {item.toLabel ?? '了解更多'} →
                    </Link>
                  )}
                </article>
              ))}
            </div>
          </div>
        </section>
      ))}

      <section className="qql-section qql-section--surface">
        <div className="qql-container">
          <span className="qql-eyebrow">刻意不做</span>
          <h2 className="qql-h2">现阶段明确不提供的东西</h2>
          <p className="qql-lead">
            少做一点、说清楚一点，比在首页挂一堆点不动的入口更可信。
          </p>
          <div className="qql-grid qql-grid--2" style={{marginTop: '1.5rem'}}>
            {notIncluded.map(([title, reason]) => (
              <div key={title} className="qql-card">
                <h3>{title}</h3>
                <p>{reason}</p>
              </div>
            ))}
          </div>
          <div className="qql-actions" style={{marginTop: '1.75rem'}}>
            <Link className="qql-btn qql-btn--ghost" to="/architecture">
              接下来看架构与边界 →
            </Link>
          </div>
        </div>
      </section>
    </Layout>
  );
}
