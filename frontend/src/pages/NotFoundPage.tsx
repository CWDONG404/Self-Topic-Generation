import { ArrowLeft } from 'lucide-react';
import { Link } from 'react-router-dom';
import { buttonVariants } from '../components/ui/Button';

export function NotFoundPage() {
  return <div className="flex min-h-[70vh] flex-col items-center justify-center text-center"><p className="font-display text-8xl font-semibold text-pine-100">404</p><h1 className="mt-3 text-2xl font-bold text-ink">这一页不在资料里</h1><p className="mt-2 text-sm text-stone-400">链接可能已经失效，或者页面还没有生成。</p><Link to="/" className={`${buttonVariants()} mt-6`}><ArrowLeft className="h-4 w-4" />返回总览</Link></div>;
}
