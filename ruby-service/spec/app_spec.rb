# frozen_string_literal: true

require_relative 'spec_helper'
require_relative '../app/app'

RSpec.describe PolyglotAPI do
  include Rack::Test::Methods

  def app
    PolyglotAPI
  end

  describe 'GET /health' do
    it 'returns healthy status' do
      get '/health'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['status']).to eq('healthy')
    end
  end

  describe 'POST /analyze' do
    it 'accepts valid content' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'language' => 'python', 'lines' => ['def test'] })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .and_return({ 'score' => 85.0, 'issues' => [] })

      post '/analyze', { content: 'def test(): pass', path: 'test.py' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response).to have_key('summary')
    end
  end

  describe 'GET /status' do
    context 'when all services are healthy' do
      it 'returns healthy statuses for all services' do
        allow(HTTParty).to receive(:get).with('http://localhost:8080/health', timeout: 2).and_return(double(code: 200))
        allow(HTTParty).to receive(:get).with('http://localhost:8081/health', timeout: 2).and_return(double(code: 200))
        allow(HTTParty).to receive(:get).with('http://localhost:8083/health', timeout: 2).and_return(double(code: 200))

        get '/status'
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['services']['ruby']['status']).to eq('healthy')
        expect(body['services']['go']['status']).to eq('healthy')
        expect(body['services']['python']['status']).to eq('healthy')
        expect(body['services']['cache']['status']).to eq('healthy')
      end
    end

    context 'when a service is unreachable' do
      it 'marks the service as unreachable and includes the error' do
        allow(HTTParty).to receive(:get).with('http://localhost:8080/health',
                                              timeout: 2).and_raise(StandardError.new('timeout'))
        allow(HTTParty).to receive(:get).with('http://localhost:8081/health', timeout: 2).and_return(double(code: 200))
        allow(HTTParty).to receive(:get).with('http://localhost:8083/health', timeout: 2).and_return(double(code: 200))

        get '/status'
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['services']['go']['status']).to eq('unreachable')
        expect(body['services']['go']['error']).to include('timeout')
        expect(body['services']['python']['status']).to eq('healthy')
        expect(body['services']['cache']['status']).to eq('healthy')
      end
    end
  end

  describe 'GET /cache/stats' do
    it 'returns cache stats when cache service responds' do
      allow(HTTParty).to receive(:get).with('http://localhost:8083/cache/stats', timeout: 3)
                                      .and_return(double(body: { hits: 5, misses: 2 }.to_json))

      get '/cache/stats'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['hits']).to eq(5)
      expect(body['misses']).to eq(2)
    end

    it 'returns error when cache service fails' do
      allow(HTTParty).to receive(:get).with('http://localhost:8083/cache/stats', timeout: 3)
                                      .and_raise(StandardError.new('connection refused'))

      get '/cache/stats'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['error']).to include('connection refused')
    end
  end

  describe 'POST /cache/invalidate' do
    let(:headers) { { 'CONTENT_TYPE' => 'application/json' } }

    context 'with valid JSON body' do
      it 'forwards invalidate request to cache service and returns response' do
        expected_body = { success: true, cleared: 1 }
        allow(HTTParty).to receive(:post)
          .with('http://localhost:8083/cache/invalidate',
                body: { service: 'go', key: 'file1' }.to_json,
                headers: { 'Content-Type' => 'application/json' },
                timeout: 3)
          .and_return(double(body: expected_body.to_json))

        post '/cache/invalidate', { service: 'go', key: 'file1' }.to_json, headers
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['success']).to eq(true)
        expect(body['cleared']).to eq(1)
      end
    end

    context 'with form params' do
      it 'accepts form-encoded parameters' do
        expected_body = { success: true }
        allow(HTTParty).to receive(:post)
          .with('http://localhost:8083/cache/invalidate',
                body: { service: 'python', key: nil }.to_json,
                headers: { 'Content-Type' => 'application/json' },
                timeout: 3)
          .and_return(double(body: expected_body.to_json))

        post '/cache/invalidate', { 'service' => 'python' }
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['success']).to eq(true)
      end
    end

    context 'when service parameter is missing' do
      it 'returns 400 with error' do
        post '/cache/invalidate', { key: 'x' }.to_json, headers
        expect(last_response.status).to eq(400)
        body = JSON.parse(last_response.body)
        expect(body['error']).to eq('Missing service parameter')
      end
    end

    context 'when cache service call fails' do
      it 'returns error JSON' do
        allow(HTTParty).to receive(:post).and_raise(StandardError.new('boom'))
        post '/cache/invalidate', { service: 'go' }.to_json, headers
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['error']).to include('boom')
      end
    end
  end

  describe 'POST /cache/invalidate-all' do
    it 'returns services cleared when all succeed' do
      allow(HTTParty).to receive(:post).with('http://localhost:8080/cache/clear', timeout: 3).and_return(double)
      allow(HTTParty).to receive(:post).with('http://localhost:8081/cache/clear', timeout: 3).and_return(double)
      allow(HTTParty).to receive(:post).with('http://localhost:8083/cache/invalidate-all',
                                             timeout: 3).and_return(double)

      post '/cache/invalidate-all'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['message']).to eq('Cache invalidation completed')
      expect(body['cleared_services']).to contain_exactly('go', 'python', 'cache')
    end

    it 'includes failure messages for services that fail' do
      allow(HTTParty).to receive(:post).with('http://localhost:8080/cache/clear',
                                             timeout: 3).and_raise(StandardError.new('oops'))
      allow(HTTParty).to receive(:post).with('http://localhost:8081/cache/clear',
                                             timeout: 3).and_raise(StandardError.new('down'))
      allow(HTTParty).to receive(:post).with('http://localhost:8083/cache/invalidate-all',
                                             timeout: 3).and_return(double)

      post '/cache/invalidate-all'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['cleared_services']).to include('cache')
      expect(body['cleared_services'].any? { |s| s.start_with?('go (failed: oops') }).to eq(true)
      expect(body['cleared_services'].any? { |s| s.start_with?('python (failed: down') }).to eq(true)
    end
  end

  describe 'POST /diff' do
    let(:headers) { { 'CONTENT_TYPE' => 'application/json' } }

    context 'when required params are missing' do
      it 'returns 400 error' do
        post '/diff', { old_content: 'a' }.to_json, headers
        expect(last_response.status).to eq(400)
        body = JSON.parse(last_response.body)
        expect(body['error']).to eq('Missing old_content or new_content')
      end
    end

    context 'with valid params' do
      it 'returns diff and new code review' do
        allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
          .with('/diff', hash_including(old_content: 'a', new_content: 'b'))
          .and_return({ 'changes' => [{ 'op' => 'add' }] })
        allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
          .with('/review', hash_including(content: 'b'))
          .and_return({ 'score' => 75, 'issues' => [] })

        post '/diff', { old_content: 'a', new_content: 'b' }.to_json, headers
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['diff']).to be_a(Hash)
        expect(body['new_code_review']).to be_a(Hash)
      end
    end
  end

  describe 'POST /metrics' do
    let(:headers) { { 'CONTENT_TYPE' => 'application/json' } }

    context 'when content is missing' do
      it 'returns 400 error' do
        post '/metrics', {}.to_json, headers
        expect(last_response.status).to eq(400)
        body = JSON.parse(last_response.body)
        expect(body['error']).to eq('Missing content')
      end
    end

    context 'with valid content' do
      it 'returns metrics, review, and overall_quality' do
        allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
          .with('/metrics', hash_including(content: 'code'))
          .and_return({ 'complexity' => 1 })
        allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
          .with('/review', hash_including(content: 'code'))
          .and_return({ 'score' => 90, 'issues' => [1] })

        post '/metrics', { content: 'code' }.to_json, headers
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['metrics']).to include('complexity' => 1)
        expect(body['review']).to include('score' => 90)
        expect(body['overall_quality']).to eq(30.0)
      end
    end
  end

  describe 'private helper methods' do
    let(:instance) { app.new }

    describe '#detect_language' do
      it 'detects language by file extension' do
        expect(instance.send(:detect_language, 'file.go')).to eq('go')
        expect(instance.send(:detect_language, 'script.py')).to eq('python')
        expect(instance.send(:detect_language, 'app.rb')).to eq('ruby')
        expect(instance.send(:detect_language, 'index.js')).to eq('javascript')
        expect(instance.send(:detect_language, 'app.ts')).to eq('typescript')
        expect(instance.send(:detect_language, 'Main.java')).to eq('java')
      end

      it 'returns unknown for unsupported extensions' do
        expect(instance.send(:detect_language, 'README.md')).to eq('unknown')
        expect(instance.send(:detect_language, 'noext')).to eq('unknown')
      end
    end

    describe '#calculate_quality_score' do
      it 'returns 0.0 when metrics is nil' do
        expect(instance.send(:calculate_quality_score, nil, { 'score' => 80 })).to eq(0.0)
      end

      it 'returns 0.0 when review is nil' do
        expect(instance.send(:calculate_quality_score, { 'complexity' => 1 }, nil)).to eq(0.0)
      end

      it 'returns 0.0 when metrics has error' do
        expect(instance.send(:calculate_quality_score, { 'error' => 'x' }, { 'score' => 90 })).to eq(0.0)
      end

      it 'returns 0.0 when review has error' do
        expect(instance.send(:calculate_quality_score, { 'complexity' => 0 }, { 'error' => 'y' })).to eq(0.0)
      end

      it 'calculates score with penalties and rounds, clamping to [0,100]' do
        score = instance.send(:calculate_quality_score, { 'complexity' => 1 }, { 'score' => 90, 'issues' => [1] })
        expect(score).to eq(30.0)

        high = instance.send(:calculate_quality_score, { 'complexity' => 0 }, { 'score' => 100, 'issues' => [] })
        expect(high).to eq(100)

        low = instance.send(:calculate_quality_score, { 'complexity' => 50 }, { 'score' => 10, 'issues' => [1, 2, 3] })
        expect(low).to eq(0)
      end
    end

    describe '#check_service_health' do
      it 'returns healthy when service responds with 200' do
        allow(HTTParty).to receive(:get).with('http://localhost:8080/health', timeout: 2).and_return(double(code: 200))
        res = instance.send(:check_service_health, 'http://localhost:8080')
        expect(res[:status]).to eq('healthy')
      end

      it 'returns unhealthy when service responds with non-200' do
        allow(HTTParty).to receive(:get).with('http://localhost:8080/health', timeout: 2).and_return(double(code: 500))
        res = instance.send(:check_service_health, 'http://localhost:8080')
        expect(res[:status]).to eq('unhealthy')
      end

      it 'returns unreachable when an error occurs' do
        allow(HTTParty).to receive(:get).with('http://localhost:8080/health',
                                              timeout: 2).and_raise(StandardError.new('boom'))
        res = instance.send(:check_service_health, 'http://localhost:8080')
        expect(res[:status]).to eq('unreachable')
        expect(res[:error]).to include('boom')
      end
    end

    describe '#call_go_service' do
      it 'posts to go service and parses JSON body' do
        allow(HTTParty).to receive(:post)
          .with('http://localhost:8080/metrics',
                body: { a: 1 }.to_json,
                headers: { 'Content-Type' => 'application/json' },
                timeout: 5)
          .and_return(double(body: { ok: true }.to_json))
        res = instance.send(:call_go_service, '/metrics', { a: 1 })
        expect(res['ok']).to eq(true)
      end

      it 'returns error hash on exceptions' do
        allow(HTTParty).to receive(:post).and_raise(StandardError.new('failed'))
        res = instance.send(:call_go_service, '/metrics', { a: 1 })
        expect(res[:error]).to include('failed')
      end
    end

    describe '#call_python_service' do
      it 'posts to python service and parses JSON body' do
        allow(HTTParty).to receive(:post)
          .with('http://localhost:8081/review',
                body: { code: 'x' }.to_json,
                headers: { 'Content-Type' => 'application/json' },
                timeout: 5)
          .and_return(double(body: { score: 88 }.to_json))
        res = instance.send(:call_python_service, '/review', { code: 'x' })
        expect(res['score']).to eq(88)
      end

      it 'returns error hash on exceptions' do
        allow(HTTParty).to receive(:post).and_raise(StandardError.new('nope'))
        res = instance.send(:call_python_service, '/review', { code: 'x' })
        expect(res[:error]).to include('nope')
      end
    end
  end
end
