# frozen_string_literal: true

require 'rails_helper'
require 'rack/test'
require 'json'
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

    it 'returns 400 when content is missing' do
      post '/analyze', { path: 'file.rb' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing content')
    end

    it 'falls back to params when JSON parsing fails' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'language' => 'ruby', 'lines' => ['puts hello'] })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .and_return({ 'score' => 70.0, 'issues' => [] })

      post '/analyze?content=puts+%22hello%22&path=test.rb', 'invalid-json', 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['summary']['language']).to eq('ruby')
    end
  end

  describe 'GET /status' do
    it 'aggregates service health statuses as healthy' do
      allow(HTTParty).to receive(:get).and_return(double(code: 200))
      get '/status'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['services']['ruby']['status']).to eq('healthy')
      expect(json_response['services']['go']['status']).to eq('healthy')
      expect(json_response['services']['python']['status']).to eq('healthy')
    end

    it 'marks a service as unreachable on error' do
      go_url = app.settings.go_service_url
      py_url = app.settings.python_service_url
      allow(HTTParty).to receive(:get) do |url, *_args|
        if url == "#{go_url}/health"
          raise StandardError, 'timeout'
        elsif url == "#{py_url}/health"
          double(code: 200)
        else
          double(code: 200)
        end
      end

      get '/status'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['services']['go']['status']).to eq('unreachable')
      expect(json_response['services']['go']['error']).to match(/timeout/)
      expect(json_response['services']['python']['status']).to eq('healthy')
    end
  end

  describe 'POST /diff' do
    it 'returns 400 when old_content or new_content is missing' do
      post '/diff', { old_content: 'old' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing old_content or new_content')
    end

    it 'returns diff and new_code_review on success' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/diff', hash_including(:old_content, :new_content))
        .and_return({ 'changes' => [{ 'line' => 1, 'type' => 'added' }] })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(:content))
        .and_return({ 'score' => 88, 'issues' => [] })

      post '/diff', { old_content: 'a', new_content: 'b' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body).to have_key('diff')
      expect(body).to have_key('new_code_review')
      expect(body['diff']['changes']).to be_an(Array)
      expect(body['new_code_review']['score']).to eq(88)
    end

    it 'calls python review with new_content' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'changes' => [] })
      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'new code'))
        .and_return({ 'score' => 90, 'issues' => [] })

      post '/diff', { old_content: 'old code', new_content: 'new code' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
    end
  end

  describe 'POST /metrics' do
    it 'returns 400 when content is missing' do
      post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing content')
    end

    it 'returns metrics, review and overall_quality' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/metrics', hash_including(:content))
        .and_return({ 'complexity' => 1 })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(:content))
        .and_return({ 'score' => 90, 'issues' => ['minor'] })

      post '/metrics', { content: 'def x(): pass' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['metrics']['complexity']).to eq(1)
      expect(json_response['review']['score']).to eq(90)
      expect(json_response['overall_quality']).to eq(30.0)
    end
  end

  describe 'POST /dashboard' do
    it 'returns 400 when files array is missing or empty' do
      post '/dashboard', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing files array')
    end

    it 'returns dashboard statistics and computed health score' do
      file_stats = {
        'total_files' => 4,
        'total_lines' => 100,
        'languages' => { 'ruby' => 2 }
      }
      review_stats = {
        'average_score' => 80.0,
        'total_issues' => 4,
        'average_complexity' => 0.5
      }

      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/statistics', hash_including(:files))
        .and_return(file_stats)
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/statistics', hash_including(:files))
        .and_return(review_stats)

      files = [{ path: 'a.rb', content: '1' }, { path: 'b.py', content: '2' }]
      post '/dashboard', { files: files }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response).to have_key('timestamp')
      expect(json_response['file_statistics']['total_files']).to eq(4)
      expect(json_response['review_statistics']['total_issues']).to eq(4)
      expect(json_response['summary']['health_score']).to eq(63.0)
    end

    it 'returns health_score 0.0 when stats contain errors' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'error' => 'service down' })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .and_return({ 'average_score' => 80, 'total_issues' => 1 })

      post '/dashboard', { files: [{ path: 'x.rb', content: 'puts' }] }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['summary']['health_score']).to eq(0.0)
    end
  end

  describe 'private helpers' do
    let(:api_instance) { PolyglotAPI.new }

    describe '#detect_language' do
      it 'detects ruby from file extension' do
        expect(api_instance.send(:detect_language, 'file.rb')).to eq('ruby')
      end

      it 'detects python from file extension' do
        expect(api_instance.send(:detect_language, 'script.py')).to eq('python')
      end

      it 'returns unknown for unrecognized extensions' do
        expect(api_instance.send(:detect_language, 'archive.xyz')).to eq('unknown')
      end
    end

    describe '#calculate_quality_score' do
      it 'returns 0.0 when metrics is nil' do
        expect(api_instance.send(:calculate_quality_score, nil, { 'score' => 90 })).to eq(0.0)
      end

      it 'returns 0.0 when review has error' do
        expect(api_instance.send(:calculate_quality_score, { 'complexity' => 1 }, { 'error' => 'fail' })).to eq(0.0)
      end

      it 'clamps to 100 when score exceeds 100' do
        score = api_instance.send(:calculate_quality_score, { 'complexity' => 0 }, { 'score' => 150, 'issues' => [] })
        expect(score).to eq(100)
      end

      it 'computes expected score with penalties' do
        score = api_instance.send(:calculate_quality_score, { 'complexity' => 2 }, { 'score' => 95, 'issues' => ['a'] })
        expect(score).to eq(25.0)
      end

      it 'clamps to 0 when penalties exceed score' do
        score = api_instance.send(:calculate_quality_score, { 'complexity' => 10 },
                                  { 'score' => 20, 'issues' => %w[a b] })
        expect(score).to eq(0)
      end
    end

    describe '#calculate_dashboard_health_score' do
      it 'returns 0.0 when file_stats has error' do
        expect(api_instance.send(:calculate_dashboard_health_score, { 'error' => 'x' },
                                 { 'average_score' => 80 })).to eq(0.0)
      end

      it 'clamps between 0 and 100' do
        high = api_instance.send(:calculate_dashboard_health_score, { 'total_files' => 1 },
                                 { 'average_score' => 150, 'total_issues' => 0, 'average_complexity' => 0 })
        low = api_instance.send(:calculate_dashboard_health_score, { 'total_files' => 1 },
                                { 'average_score' => 5, 'total_issues' => 100, 'average_complexity' => 10 })
        expect(high).to eq(100)
        expect(low).to eq(0)
      end

      it 'computes expected health score' do
        file_stats = { 'total_files' => 4 }
        review_stats = { 'average_score' => 80.0, 'total_issues' => 4, 'average_complexity' => 0.5 }
        score = api_instance.send(:calculate_dashboard_health_score, file_stats, review_stats)
        expect(score).to eq(63.0)
      end
    end
  end
end
